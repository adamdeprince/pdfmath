from pdfmath.geometry.bbox import BBox
from pdfmath.geometry.index import (SpatialIndex, baseline_clusters,
                                    horizontal_bands, same_baseline, vertical_bands)


def test_bbox_basics():
    b = BBox.from_baseline(10, 100, width=5, height=4, depth=2)
    assert (b.x0, b.y0, b.x1, b.y1) == (10, 98, 15, 104)
    assert b.width == 5 and b.height == 6
    assert b.contains_point(12, 100)


def test_overlap_is_signed_so_gaps_are_measurable():
    a = BBox(0, 0, 10, 10)
    b = BBox(15, 0, 20, 10)
    assert a.overlap_x(b) == -5          # the gap between them
    assert a.overlap_y(b) == 10


def test_union_and_containment():
    a, b = BBox(0, 0, 10, 10), BBox(5, 5, 20, 20)
    assert BBox.union([a, b]) == BBox(0, 0, 20, 20)
    assert BBox(0, 0, 30, 30).contains(a)


def test_spatial_index_queries():
    boxes = [BBox(0, 0, 5, 5), BBox(10, 0, 15, 5), BBox(0, 10, 5, 15)]
    idx = SpatialIndex(list(boxes), lambda b: b)
    assert len(idx.inside(BBox(-1, -1, 16, 6))) == 2
    assert idx.above(BBox(0, 0, 5, 5)) == [boxes[2]]
    assert idx.nearest_right(BBox(0, 0, 5, 5), tol_y=1) is boxes[1]


def test_baseline_clusters_are_top_down():
    # Groups come back highest-first, and members within a group are ordered by
    # descending baseline too.
    groups = baseline_clusters([100.0, 100.01, 88.0], tol=0.05)
    assert [sorted(g) for g in groups] == [[0, 1], [2]]
    assert groups[0][0] == 1


def test_bands():
    boxes = [BBox(0, 20, 5, 25), BBox(0, 0, 5, 5), BBox(6, 0, 9, 5)]
    assert vertical_bands(boxes, gap=1.0) == [[0], [1, 2]]
    assert horizontal_bands(boxes, gap=0.5) == [[0, 1], [2]]


def test_same_baseline():
    assert same_baseline(100.0, 100.02, tol=0.05)
    assert not same_baseline(100.0, 101.0, tol=0.05)
