"""
ML Terrain Model - Learn natural heightmaps from real WoW Azeroth data.

Two-layer system: CNN target + iterative vertex relaxation.

1. Coons patch (pure NumPy) - bilinear transfinite interpolation from 4 edge
   arrays, producing a smooth base surface.
2. CNN target (~60K params) - trained on 687 real Azeroth heightmaps, predicts
   what natural terrain looks like given edges.
3. Vertex relaxation - iteratively adjusts vertices toward the CNN target,
   with constrained range and recursive neighbor propagation.

Graceful fallback: without PyTorch the CNN target is unavailable.
The relaxer still works using only Laplacian smoothing against the Coons base.

Usage:
    from world_builder.terrain_model import TerrainGenerator

    gen = TerrainGenerator("world_builder/terrain_model.pth")
    heightmap = gen.generate(north, south, west, east)
"""

import logging
import os

import numpy as np

log = logging.getLogger(__name__)

# Try to import torch; fall back gracefully
try:
    import torch
    import torch.nn as nn
    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False

_RES = 129  # WoW ADT heightmap resolution per tile


# ---------------------------------------------------------------------------
# Layer 1: Coons Patch (pure NumPy)
# ---------------------------------------------------------------------------

def coons_patch(north, south, west, east):
    """Bilinear transfinite interpolation from 4 boundary curves.

    C(u,v) = (1-v)*N(u) + v*S(u) + (1-u)*W(v) + u*E(v)
             - [(1-u)(1-v)*NW + u(1-v)*NE + (1-u)v*SW + uv*SE]

    Args:
        north: array(129) - top edge (row 0, left-to-right).
        south: array(129) - bottom edge (row 128, left-to-right).
        west:  array(129) - left edge (col 0, top-to-bottom).
        east:  array(129) - right edge (col 128, top-to-bottom).

    Returns:
        np.ndarray(129, 129) - interpolated surface.
    """
    north = np.asarray(north, dtype=np.float64)
    south = np.asarray(south, dtype=np.float64)
    west = np.asarray(west, dtype=np.float64)
    east = np.asarray(east, dtype=np.float64)

    v = np.linspace(0.0, 1.0, _RES)[:, None]  # (129, 1)
    u = np.linspace(0.0, 1.0, _RES)[None, :]  # (1, 129)

    # Boundary interpolation
    P1 = (1.0 - v) * north[None, :] + v * south[None, :]
    P2 = (1.0 - u) * west[:, None] + u * east[:, None]

    # Corner correction
    P12 = ((1.0 - v) * (1.0 - u) * north[0]
           + (1.0 - v) * u * north[_RES - 1]
           + v * (1.0 - u) * south[0]
           + v * u * south[_RES - 1])

    return P1 + P2 - P12


def enforce_corner_consistency(edges):
    """Average corner values where edges share a vertex.

    Modifies edge arrays in-place so corners are consistent:
    NW = (north[0] + west[0]) / 2, NE = (north[128] + east[0]) / 2, etc.

    Args:
        edges: dict with keys 'north', 'south', 'west', 'east',
               each a numpy array(129). Missing keys are skipped.
    """
    pairs = [
        ('north', 0, 'west', 0),       # NW corner
        ('north', -1, 'east', 0),      # NE corner
        ('south', 0, 'west', -1),      # SW corner
        ('south', -1, 'east', -1),     # SE corner
    ]
    for k1, i1, k2, i2 in pairs:
        if k1 in edges and k2 in edges:
            avg = (edges[k1][i1] + edges[k2][i2]) / 2.0
            edges[k1][i1] = avg
            edges[k2][i2] = avg


def resolve_missing_edges(edge_arrays, default_height=0.5):
    """Fill missing edges with best available data.

    Priority: real neighbor > mirror from opposite > mean of available > flat.

    Args:
        edge_arrays: dict with optional keys 'north', 'south', 'west', 'east'.
        default_height: fallback constant if no edges at all.

    Returns:
        dict with all four keys present, each a numpy array(129).
    """
    opposites = {
        'north': 'south', 'south': 'north',
        'west': 'east', 'east': 'west',
    }
    result = {}
    available = [np.asarray(v, dtype=np.float64)
                 for v in edge_arrays.values()]

    if available:
        global_mean = float(np.mean(np.concatenate(available)))
    else:
        global_mean = default_height

    for key in ('north', 'south', 'west', 'east'):
        if key in edge_arrays:
            result[key] = np.asarray(edge_arrays[key], dtype=np.float64).copy()
        elif opposites[key] in edge_arrays:
            result[key] = np.asarray(
                edge_arrays[opposites[key]], dtype=np.float64).copy()
        else:
            result[key] = np.full(_RES, global_mean, dtype=np.float64)

    enforce_corner_consistency(result)
    return result


# ---------------------------------------------------------------------------
# Layer 2: Residual Detail Network (PyTorch, ~60K params)
# ---------------------------------------------------------------------------

if _HAS_TORCH:

    class TerrainResidualNet(nn.Module):
        """Multi-scale dilated CNN predicting a full target heightmap from Coons base.

        Architecture: 6 dilated conv layers → concatenated → fuse to single channel.
        Maintains full 129x129 resolution throughout (no pooling).

        Input:  (B, 1, 129, 129) normalised Coons base
        Output: (B, 1, 129, 129) predicted target heightmap
        """

        def __init__(self):
            super().__init__()
            dilations = [1, 2, 4, 8, 16, 32]
            self.layers = nn.ModuleList()
            in_ch = 1
            for d in dilations:
                self.layers.append(nn.Sequential(
                    nn.Conv2d(in_ch, 32, 3, padding=d, dilation=d),
                    nn.BatchNorm2d(32),
                    nn.ReLU(inplace=True),
                ))
                in_ch = 32

            # Fuse concatenated multi-scale features
            self.fuse = nn.Sequential(
                nn.Conv2d(32 * len(dilations), 64, 1),
                nn.BatchNorm2d(64),
                nn.ReLU(inplace=True),
                nn.Conv2d(64, 1, 1),
            )

        def forward(self, x):
            features = []
            h = x
            for layer in self.layers:
                h = layer(h)
                features.append(h)
            cat = torch.cat(features, dim=1)
            return self.fuse(cat)


# ---------------------------------------------------------------------------
# Layer 3: Iterative Vertex Relaxation (pure NumPy)
# ---------------------------------------------------------------------------

class TerrainRelaxer:
    """Iteratively relaxes vertices toward a learned target with constraints.

    Physics analogy: each vertex is a mass on a spring network.
    - Model spring: pulls toward CNN target (what terrain "should" look like)
    - Neighbor springs: pulls toward average of 4 adjacent vertices (smoothness)
    - Edge pins: boundary vertices are fixed to neighbor tile data
    - User pins: manually set vertices stay fixed
    - Range clamp: no vertex can move more than max_delta from Coons base

    Args:
        coons_base: (129,129) Coons patch surface.
        target: (129,129) CNN-predicted target (or coons_base for fallback).
        pinned_edges: dict with keys 'north','south','west','east',
                      each array(129). Missing = edge is free.
        max_delta: max displacement from base in world units.
        alpha: model attraction strength.
        beta: neighbor smoothing strength.
        damping: iteration damping factor.
    """

    def __init__(self, coons_base, target, pinned_edges,
                 max_delta=50.0, alpha=0.4, beta=0.3, damping=0.6):
        self.base = np.asarray(coons_base, dtype=np.float64)
        self.target = np.asarray(target, dtype=np.float64)
        self.current = self.base.copy()
        self.max_delta = float(max_delta)
        self.alpha = float(alpha)
        self.beta = float(beta)
        self.damping = float(damping)

        # Pin mask: True = free to move, False = pinned
        self.pin_mask = np.ones((_RES, _RES), dtype=bool)
        # Store pinned values for restoration
        self._pinned_values = np.zeros((_RES, _RES), dtype=np.float64)

        self._setup_edge_pins(pinned_edges)

    def _setup_edge_pins(self, pinned_edges):
        """Pin edge vertices from neighbor data."""
        if 'north' in pinned_edges:
            arr = np.asarray(pinned_edges['north'], dtype=np.float64)
            self.current[0, :] = arr
            self._pinned_values[0, :] = arr
            self.pin_mask[0, :] = False
        if 'south' in pinned_edges:
            arr = np.asarray(pinned_edges['south'], dtype=np.float64)
            self.current[_RES - 1, :] = arr
            self._pinned_values[_RES - 1, :] = arr
            self.pin_mask[_RES - 1, :] = False
        if 'west' in pinned_edges:
            arr = np.asarray(pinned_edges['west'], dtype=np.float64)
            self.current[:, 0] = arr
            self._pinned_values[:, 0] = arr
            self.pin_mask[:, 0] = False
        if 'east' in pinned_edges:
            arr = np.asarray(pinned_edges['east'], dtype=np.float64)
            self.current[:, _RES - 1] = arr
            self._pinned_values[:, _RES - 1] = arr
            self.pin_mask[:, _RES - 1] = False

    def pin_vertex(self, row, col, height):
        """Pin a vertex to a specific height (user edit or entity flatten)."""
        height = float(height)
        self.current[row, col] = height
        self._pinned_values[row, col] = height
        self.pin_mask[row, col] = False

    def unpin_vertex(self, row, col):
        """Release a previously pinned interior vertex."""
        # Don't unpin edge vertices
        if row == 0 or row == _RES - 1 or col == 0 or col == _RES - 1:
            return
        self.pin_mask[row, col] = True

    def relax(self, iterations=150, early_stop_threshold=0.01):
        """Iteratively move free vertices toward target.

        Per iteration, for each free vertex:
          force = alpha * (target - current) + beta * (neighbor_avg - current)
          current += damping * force
          clamp displacement to +/-max_delta from base

        Args:
            iterations: max number of relaxation steps.
            early_stop_threshold: stop if max vertex change < this.

        Returns:
            np.ndarray(129, 129) - relaxed heightmap.
        """
        for _ in range(iterations):
            # Discrete Laplacian via padded array
            padded = np.pad(self.current, 1, mode='edge')
            neighbor_avg = (padded[:-2, 1:-1] + padded[2:, 1:-1] +
                            padded[1:-1, :-2] + padded[1:-1, 2:]) / 4.0

            # Combined force
            model_force = self.target - self.current
            smooth_force = neighbor_avg - self.current
            force = self.alpha * model_force + self.beta * smooth_force

            # Apply only to free vertices
            update = self.damping * force
            update[~self.pin_mask] = 0.0

            # Early stopping check
            max_change = float(np.max(np.abs(update)))
            if max_change < early_stop_threshold:
                break

            # Update
            self.current += update

            # Clamp displacement from base
            delta = self.current - self.base
            np.clip(delta, -self.max_delta, self.max_delta, out=delta)
            self.current = self.base + delta

            # Restore pinned values
            self.current[~self.pin_mask] = self._pinned_values[~self.pin_mask]

        return self.current


# ---------------------------------------------------------------------------
# TerrainGenerator: combines all three layers
# ---------------------------------------------------------------------------

class TerrainGenerator:
    """Generate natural-looking heightmaps using CNN target + relaxation.

    Loads a trained TerrainResidualNet model (.pth file) and uses it to
    predict what terrain should look like, then converges toward it via
    vertex relaxation with boundary constraints.

    Falls back to Coons + Laplacian smoothing if torch is unavailable
    or no model file is provided.

    Args:
        model_path: path to terrain_model.pth (optional).
        max_delta: max displacement from Coons base in world units.
        alpha: model attraction strength for relaxation.
        beta: neighbor smoothing strength.
        damping: relaxation damping factor.
        iterations: number of relaxation iterations.
    """

    def __init__(self, model_path=None, max_delta=50.0,
                 alpha=0.4, beta=0.3, damping=0.6, iterations=150):
        self.max_delta = max_delta
        self.alpha = alpha
        self.beta = beta
        self.damping = damping
        self.iterations = iterations

        self._model = None
        self._device = None

        if model_path and _HAS_TORCH and os.path.isfile(model_path):
            self._load_model(model_path)
        elif model_path and not _HAS_TORCH:
            log.warning("PyTorch not installed, falling back to Coons + "
                        "Laplacian smoothing (no learned terrain features)")
        elif model_path and not os.path.isfile(model_path):
            log.warning("Model file not found: %s — falling back to Coons "
                        "+ Laplacian smoothing", model_path)

    def _load_model(self, model_path):
        """Load trained CNN weights."""
        try:
            self._device = torch.device('cpu')
            self._model = TerrainResidualNet()
            state = torch.load(model_path, map_location=self._device,
                               weights_only=True)
            self._model.load_state_dict(state)
            self._model.eval()
            log.info("Loaded terrain model from %s", model_path)
        except Exception as e:
            log.warning("Failed to load terrain model: %s", e)
            self._model = None

    @property
    def has_model(self):
        """Whether a trained CNN model is loaded."""
        return self._model is not None

    def generate(self, north, south, west, east,
                 pinned_edges=None, extra_pins=None):
        """Generate a 129x129 heightmap from boundary edges.

        Args:
            north, south, west, east: array(129) boundary heights
                (already in world units).
            pinned_edges: optional dict overriding which edges to pin
                during relaxation. If None, pins all four edges.
            extra_pins: optional list of (row, col, height) for user pins.

        Returns:
            np.ndarray(129, 129) - final heightmap in world units.
        """
        north = np.asarray(north, dtype=np.float64)
        south = np.asarray(south, dtype=np.float64)
        west = np.asarray(west, dtype=np.float64)
        east = np.asarray(east, dtype=np.float64)

        # Step 1: Coons patch base
        base = coons_patch(north, south, west, east)

        # Step 2: CNN target (or fallback to base)
        target = self._predict_target(base, north, south, west, east)

        # Step 3: Relaxation
        if pinned_edges is None:
            pinned_edges = {
                'north': north, 'south': south,
                'west': west, 'east': east,
            }

        relaxer = TerrainRelaxer(
            coons_base=base,
            target=target,
            pinned_edges=pinned_edges,
            max_delta=self.max_delta,
            alpha=self.alpha,
            beta=self.beta,
            damping=self.damping,
        )

        if extra_pins:
            for row, col, height in extra_pins:
                relaxer.pin_vertex(row, col, height)

        return relaxer.relax(iterations=self.iterations)

    def _predict_target(self, base, north, south, west, east):
        """Run CNN to predict target heightmap, or return base as fallback.

        Normalisation: per-tile to [0, 1] using edge-derived range with
        30% margin for interior features.
        """
        if self._model is None:
            return base.copy()

        # Compute normalisation range from edges
        all_edges = np.concatenate([north, south, west, east])
        edge_min = float(all_edges.min())
        edge_max = float(all_edges.max())
        h_range = edge_max - edge_min
        if h_range < 0.01:
            h_range = 1.0

        # Add margin for interior features
        norm_min = edge_min - 0.15 * h_range
        norm_max = edge_max + 0.15 * h_range
        norm_range = norm_max - norm_min
        if norm_range < 0.01:
            norm_range = 1.0

        # Normalise base to [0, 1]
        base_norm = (base - norm_min) / norm_range
        np.clip(base_norm, 0.0, 1.0, out=base_norm)

        # Run CNN
        with torch.no_grad():
            inp = torch.from_numpy(base_norm).float().unsqueeze(0).unsqueeze(0)
            inp = inp.to(self._device)
            out = self._model(inp)
            target_norm = out.squeeze(0).squeeze(0).cpu().numpy()

        # Denormalise back to world units
        target = target_norm * norm_range + norm_min

        return target
