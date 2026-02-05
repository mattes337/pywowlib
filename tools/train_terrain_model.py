"""
Train the terrain residual CNN on real Azeroth heightmaps.

Extracts heightmaps from WoW MPQ archives, trains a small CNN (~60K params)
to predict natural terrain from Coons patch base surfaces, and saves the
model weights.

Training pairs:
    Input:  normalised Coons base (computed from tile's 4 edges)
    Target: normalised real heightmap (the actual Azeroth terrain)

Data augmentation: 4 rotations x 2 flips = 8x per tile (~5500 samples).
Loss: MSE on interior vertices (excluding 2-pixel border).

Usage:
    python tools/train_terrain_model.py \\
        --wow-data "G:\\WoW AzerothCore\\Data" \\
        --output world_builder/terrain_model.pth \\
        --epochs 200 --batch-size 16

Requires: torch, numpy, mpyq
"""

import argparse
import os
import struct
import sys

# Add project root and world_builder dir to path so we can import
# terrain_model directly (avoids triggering world_builder/__init__.py
# which pulls in Pillow and other heavy deps not needed for training).
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, 'world_builder'))

import numpy as np

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import Dataset, DataLoader
except ImportError:
    print("ERROR: PyTorch is required for training.")
    print("  pip install torch --index-url https://download.pytorch.org/whl/cpu")
    sys.exit(1)

try:
    import mpyq
except ImportError:
    print("ERROR: mpyq is required for MPQ extraction.")
    print("  pip install mpyq")
    sys.exit(1)

# Import directly from the module file, not through __init__.py
from terrain_model import (
    coons_patch, enforce_corner_consistency, TerrainResidualNet,
)


# ---------------------------------------------------------------------------
# ADT heightmap extraction (reused from redesign_goldshire.py)
# ---------------------------------------------------------------------------

_RES = 129


def _read_heightmap_from_adt_bytes(adt_bytes):
    """Parse raw ADT binary and extract 129x129 absolute heightmap.

    Reads MCNK base position.z and adds MCVT offsets to get true heights.
    """
    heightmap = np.zeros((_RES, _RES), dtype=np.float64)
    data = adt_bytes
    mcnk_magic = b'KNCM'
    mcvt_magic = b'TVCM'

    chunk_idx = 0
    pos = 0
    while pos < len(data) - 8 and chunk_idx < 256:
        if data[pos:pos + 4] == mcnk_magic:
            mcnk_size = struct.unpack_from('<I', data, pos + 4)[0]
            mcnk_start = pos + 8

            chunk_row = chunk_idx // 16
            chunk_col = chunk_idx % 16

            base_z = struct.unpack_from('<f', data, mcnk_start + 0x70)[0]

            inner_pos = mcnk_start + 128
            mcnk_end = mcnk_start + mcnk_size

            while inner_pos < mcnk_end - 8:
                if data[inner_pos:inner_pos + 4] == mcvt_magic:
                    heights = struct.unpack_from('<145f', data, inner_pos + 8)
                    idx = 0
                    for irow in range(17):
                        if irow % 2 == 0:
                            orow = irow // 2
                            grow = chunk_row * 8 + orow
                            for col in range(9):
                                gcol = chunk_col * 8 + col
                                if grow < _RES and gcol < _RES:
                                    heightmap[grow, gcol] = base_z + heights[idx]
                                idx += 1
                        else:
                            idx += 8
                    break
                inner_pos += 1

            chunk_idx += 1
            pos = mcnk_start + mcnk_size
        else:
            pos += 1

    return heightmap


def extract_all_heightmaps(wow_data_dir, map_name="Azeroth"):
    """Extract all heightmaps for a map from MPQ archives.

    Scans common.MPQ, common-2.MPQ, patch.MPQ, patch-2.MPQ, patch-3.MPQ
    (higher patch = higher priority override).

    Args:
        wow_data_dir: path to WoW Data directory.
        map_name: WoW map name (default "Azeroth").

    Returns:
        dict {(tile_x, tile_y): np.ndarray(129, 129)}
    """
    # Search order: lower priority first, higher priority overwrites
    mpq_names = ['common.MPQ', 'common-2.MPQ', 'patch.MPQ',
                 'patch-2.MPQ', 'patch-3.MPQ']

    # Azeroth tile range (only populated tiles)
    # ADT files are named Azeroth_{x}_{y}.adt with x,y in 0..63
    adt_prefix = "World\\Maps\\{}\\{}_".format(map_name, map_name)

    heightmaps = {}
    total_extracted = 0

    for mpq_name in mpq_names:
        mpq_path = os.path.join(wow_data_dir, mpq_name)
        if not os.path.isfile(mpq_path):
            continue

        print("  Scanning {}...".format(mpq_name))
        try:
            archive = mpyq.MPQArchive(mpq_path)
        except Exception as e:
            print("    WARNING: Failed to open {}: {}".format(mpq_name, e))
            continue

        # List files via (listfile) — mpyq.files property is broken on
        # Python 3 for large WoW MPQs, but reading (listfile) directly works.
        file_list = []
        try:
            file_list = archive.files or []
        except Exception:
            pass

        if not file_list:
            try:
                listfile_bytes = archive.read_file('(listfile)')
                if listfile_bytes:
                    file_list = listfile_bytes.decode(
                        'utf-8', errors='replace').splitlines()
                    file_list = [f.strip() for f in file_list if f.strip()]
            except Exception:
                pass

        if not file_list:
            continue

        count = 0
        for raw_filename in file_list:
            if not raw_filename:
                continue
            # Normalise bytes to str (mpyq may return either)
            if isinstance(raw_filename, bytes):
                filename = raw_filename.decode('utf-8', errors='replace')
            else:
                filename = raw_filename

            # Match pattern: World\Maps\Azeroth\Azeroth_X_Y.adt
            fname_lower = filename.lower()
            prefix_lower = adt_prefix.lower()
            if not fname_lower.startswith(prefix_lower):
                continue
            if not fname_lower.endswith('.adt'):
                continue

            # Parse coordinates from filename
            basename = filename[len(adt_prefix):]
            basename = basename.replace('.adt', '').replace('.ADT', '')
            parts = basename.split('_')
            if len(parts) != 2:
                continue
            try:
                tx = int(parts[0])
                ty = int(parts[1])
            except ValueError:
                continue

            # Extract ADT bytes
            try:
                adt_bytes = archive.read_file(filename)
                if not adt_bytes or len(adt_bytes) < 1024:
                    continue
            except Exception:
                continue

            hm = _read_heightmap_from_adt_bytes(adt_bytes)

            # Skip ocean-only tiles (near-zero height range)
            h_range = float(hm.max() - hm.min())
            if h_range < 0.1:
                continue

            heightmaps[(tx, ty)] = hm
            count += 1

        total_extracted += count
        if count > 0:
            print("    Extracted {} tiles".format(count))

    print("  Total unique tiles: {}".format(len(heightmaps)))
    return heightmaps


# ---------------------------------------------------------------------------
# Dataset with augmentation
# ---------------------------------------------------------------------------

def _make_training_pair(heightmap):
    """Create (coons_base, target) training pair from a real heightmap.

    Both are normalised to [0, 1] per-tile.

    Returns:
        (base_norm, target_norm) each np.ndarray(129, 129) in [0, 1]
    """
    h_min = float(heightmap.min())
    h_max = float(heightmap.max())
    h_range = h_max - h_min
    if h_range < 0.01:
        h_range = 1.0

    target_norm = (heightmap - h_min) / h_range

    # Extract edges from normalised heightmap
    north = target_norm[0, :]
    south = target_norm[_RES - 1, :]
    west = target_norm[:, 0]
    east = target_norm[:, _RES - 1]

    base_norm = coons_patch(north, south, west, east)
    np.clip(base_norm, 0.0, 1.0, out=base_norm)

    return base_norm, target_norm


def _augment_pair(base, target):
    """Generate 8 augmented versions of a (base, target) pair.

    4 rotations x 2 (original + horizontal flip).
    Edges rotate consistently since we rotate the full arrays.

    Yields:
        (base_aug, target_aug) pairs.
    """
    for k in range(4):
        b = np.rot90(base, k)
        t = np.rot90(target, k)
        yield b.copy(), t.copy()

        # Horizontal flip
        yield np.fliplr(b).copy(), np.fliplr(t).copy()


class TerrainDataset(Dataset):
    """Dataset of (Coons base, target heightmap) training pairs with augmentation."""

    def __init__(self, heightmaps, augment=True):
        """
        Args:
            heightmaps: dict {key: np.ndarray(129, 129)} of real heightmaps.
            augment: if True, apply 8x augmentation.
        """
        self.pairs = []

        for hm in heightmaps.values():
            base, target = _make_training_pair(hm)
            if augment:
                for b_aug, t_aug in _augment_pair(base, target):
                    self.pairs.append((b_aug, t_aug))
            else:
                self.pairs.append((base, target))

        print("  Dataset size: {} samples".format(len(self.pairs)))

    def __len__(self):
        return len(self.pairs)

    def __getitem__(self, idx):
        base, target = self.pairs[idx]
        # Convert to (1, 129, 129) tensors
        base_t = torch.from_numpy(base).float().unsqueeze(0)
        target_t = torch.from_numpy(target).float().unsqueeze(0)
        return base_t, target_t


# ---------------------------------------------------------------------------
# Interior-only MSE loss
# ---------------------------------------------------------------------------

class InteriorMSELoss(nn.Module):
    """MSE loss computed only on interior vertices (excluding 2-pixel border).

    Edge vertices are already correct via the Coons patch, so training
    should focus on interior prediction quality.
    """

    def __init__(self, border=2):
        super().__init__()
        self.border = border

    def forward(self, pred, target):
        b = self.border
        p = pred[:, :, b:-b, b:-b]
        t = target[:, :, b:-b, b:-b]
        return nn.functional.mse_loss(p, t)


# ---------------------------------------------------------------------------
# Training loop
# ---------------------------------------------------------------------------

def train(heightmaps, output_path, epochs=200, batch_size=16, lr=1e-3,
          val_split=0.1, patience=30):
    """Train the TerrainResidualNet on extracted heightmaps.

    Args:
        heightmaps: dict {key: np.ndarray(129, 129)}.
        output_path: where to save the best model weights.
        epochs: max training epochs.
        batch_size: training batch size.
        lr: initial learning rate.
        val_split: fraction of data for validation.
        patience: early stopping patience (epochs without improvement).

    Returns:
        dict with training stats.
    """
    # Split into train/val by tile key
    keys = sorted(heightmaps.keys())
    np.random.shuffle(keys)
    n_val = max(1, int(len(keys) * val_split))
    val_keys = set(keys[:n_val])
    train_keys = set(keys[n_val:])

    train_hm = {k: heightmaps[k] for k in train_keys}
    val_hm = {k: heightmaps[k] for k in val_keys}

    print("  Train tiles: {}, Val tiles: {}".format(len(train_hm), len(val_hm)))

    train_ds = TerrainDataset(train_hm, augment=True)
    val_ds = TerrainDataset(val_hm, augment=False)

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True,
                              num_workers=0, drop_last=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False,
                            num_workers=0)

    # Model
    device = torch.device('cpu')
    model = TerrainResidualNet().to(device)

    # Count parameters
    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print("  Model parameters: {:,}".format(n_params))

    # Optimiser & scheduler
    optimiser = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-5)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimiser, T_max=epochs)
    criterion = InteriorMSELoss(border=2)

    # Training loop
    best_val_loss = float('inf')
    epochs_no_improve = 0
    best_state = None

    for epoch in range(1, epochs + 1):
        # Train
        model.train()
        train_loss_sum = 0.0
        train_count = 0
        for base_batch, target_batch in train_loader:
            base_batch = base_batch.to(device)
            target_batch = target_batch.to(device)

            pred = model(base_batch)
            loss = criterion(pred, target_batch)

            optimiser.zero_grad()
            loss.backward()
            optimiser.step()

            train_loss_sum += loss.item() * base_batch.size(0)
            train_count += base_batch.size(0)

        scheduler.step()
        train_loss = train_loss_sum / max(train_count, 1)

        # Validate
        model.eval()
        val_loss_sum = 0.0
        val_count = 0
        with torch.no_grad():
            for base_batch, target_batch in val_loader:
                base_batch = base_batch.to(device)
                target_batch = target_batch.to(device)

                pred = model(base_batch)
                loss = criterion(pred, target_batch)

                val_loss_sum += loss.item() * base_batch.size(0)
                val_count += base_batch.size(0)

        val_loss = val_loss_sum / max(val_count, 1)

        # Progress
        if epoch % 10 == 0 or epoch == 1:
            print("  Epoch {:3d}/{:d}  train_loss={:.6f}  val_loss={:.6f}  "
                  "lr={:.2e}".format(epoch, epochs, train_loss, val_loss,
                                     optimiser.param_groups[0]['lr']))

        # Early stopping
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.cpu().clone()
                          for k, v in model.state_dict().items()}
            epochs_no_improve = 0
        else:
            epochs_no_improve += 1
            if epochs_no_improve >= patience:
                print("  Early stopping at epoch {} (no improvement for {} "
                      "epochs)".format(epoch, patience))
                break

    # Save best model
    if best_state is not None:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        torch.save(best_state, output_path)
        print("  Saved best model to {} (val_loss={:.6f})".format(
            output_path, best_val_loss))

    return {
        'best_val_loss': best_val_loss,
        'total_epochs': epoch,
        'n_params': n_params,
        'n_train': len(train_ds),
        'n_val': len(val_ds),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Train terrain residual CNN on Azeroth heightmaps"
    )
    parser.add_argument(
        "--wow-data",
        required=True,
        help="Path to WoW Data directory containing MPQ archives",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "world_builder", "terrain_model.pth"),
        help="Output path for model weights (default: world_builder/terrain_model.pth)",
    )
    parser.add_argument("--map", default="Azeroth", help="Map name to extract")
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--val-split", type=float, default=0.1)
    parser.add_argument("--patience", type=int, default=30)

    args = parser.parse_args()

    print("=" * 60)
    print("Terrain Model Training")
    print("=" * 60)

    # Step 1: Extract heightmaps
    print("\n[1/2] Extracting heightmaps from MPQ archives...")
    heightmaps = extract_all_heightmaps(args.wow_data, args.map)

    if not heightmaps:
        print("ERROR: No heightmaps extracted. Check --wow-data path.")
        sys.exit(1)

    # Print statistics
    all_ranges = [float(hm.max() - hm.min()) for hm in heightmaps.values()]
    print("  Height ranges: min={:.1f}, max={:.1f}, mean={:.1f}".format(
        min(all_ranges), max(all_ranges), sum(all_ranges) / len(all_ranges)))

    # Step 2: Train
    print("\n[2/2] Training model...")
    stats = train(
        heightmaps,
        output_path=args.output,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        val_split=args.val_split,
        patience=args.patience,
    )

    print("\n" + "=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)
    print("  Parameters:     {:,}".format(stats['n_params']))
    print("  Train samples:  {}".format(stats['n_train']))
    print("  Val samples:    {}".format(stats['n_val']))
    print("  Epochs trained: {}".format(stats['total_epochs']))
    print("  Best val loss:  {:.6f}".format(stats['best_val_loss']))
    print("  Model saved to: {}".format(args.output))


if __name__ == "__main__":
    main()
