"""Geometry regressions use analytic intersections, not rendered pixel copies."""
import copy
import math
import unittest

import pandas as pd

from structure_preview import (LAYER_COLUMNS, PATTERN_COLUMNS, build_structure_figure,
                               clip_polygon, layer_positions, material_color, normalize_region,
                               periodic_centers, region_extents, region_polygon, section_interval)


def region(shape="circle", sx=.2, sy=.1, angle=0, cx=0, cy=0, layer="Device"):
    return normalize_region(dict(zip(PATTERN_COLUMNS, [shape, layer, "Air", cx, cy, sx, sy, angle])))


class SectionGeometryTests(unittest.TestCase):
    def test_circle_exact_chord_and_tangent(self):
        r = region(sx=1, angle=82)
        self.assertEqual(section_interval(r, 0), (-1, 1))
        lo, hi = section_interval(r, .6)
        self.assertAlmostEqual(lo, -.8)
        self.assertAlmostEqual(hi, .8)
        self.assertEqual(section_interval(r, 1), (0, 0))
        self.assertIsNone(section_interval(r, 1.001))

    def test_rotated_ellipse_endpoints_satisfy_boundary(self):
        r = region("ellipse", 2, .5, 37, .2, -.15)
        c, s = math.cos(math.radians(37)), math.sin(math.radians(37))
        for dy in (-.8, 0, .6):
            result = section_interval(r, r["cy"]+dy)
            self.assertIsNotNone(result)
            for x in result:
                dx = x-r["cx"]
                self.assertAlmostEqual(((c*dx+s*dy)/2)**2+((-s*dx+c*dy)/.5)**2, 1.)
        self.assertIsNone(section_interval(r, r["cy"]+region_extents(r)[1]+.01))

    def test_rectangle_uses_full_widths_and_rotation(self):
        r = region("rectangle", 2, 1)
        self.assertEqual(section_interval(r, 0), (-1, 1))
        self.assertIsNone(section_interval(r, .51))
        r["angle"] = 90
        lo, hi = section_interval(r, .5)
        self.assertAlmostEqual(lo, -.5)
        self.assertAlmostEqual(hi, .5)
        r["angle"] = 45
        lo, hi = section_interval(r, 0)
        self.assertAlmostEqual(lo, -math.sqrt(.5))
        self.assertAlmostEqual(hi, math.sqrt(.5))

    def test_rotated_rectangle_chord_matches_polygon_edges(self):
        r = region("rectangle", .8, .3, 27, -.1, .05)
        vertices = region_polygon(r)
        for cut in (-.1, .05, .2):
            intersections = []
            for a, b in zip(vertices, vertices[1:]+vertices[:1]):
                if min(a[1], b[1]) <= cut <= max(a[1], b[1]) and a[1] != b[1]:
                    intersections.append(a[0]+(cut-a[1])/(b[1]-a[1])*(b[0]-a[0]))
            result = section_interval(r, cut)
            self.assertAlmostEqual(result[0], min(intersections))
            self.assertAlmostEqual(result[1], max(intersections))

    def test_periodic_boundary_and_far_centre_are_equivalent(self):
        r = region(sx=.12, cx=.49)
        centres = periodic_centers(r, 1, 1, (-.5, .5, 0, 0))
        self.assertEqual(len(centres), 2)
        self.assertAlmostEqual(centres[0][0], -.51)
        self.assertAlmostEqual(centres[1][0], .49)
        r["cx"] += 20
        shifted = periodic_centers(r, 1, 1, (-.5, .5, 0, 0))
        for a, b in zip(centres, shifted):
            self.assertAlmostEqual(a[0], b[0])
            self.assertAlmostEqual(a[1], b[1])

    def test_periodic_rotated_extent_includes_neighbor_centres(self):
        r = region("ellipse", .45, .08, 45, .4, .4)
        centres = periodic_centers(r, 1, 1, (-.5, .5, -.5, .5))
        self.assertEqual(len(centres), 4)
        self.assertTrue(any(cx < -.5 and cy < -.5 for cx, cy in centres))

    def test_clipping_and_copy_safety(self):
        polygon = clip_polygon([(-1, -.1), (1, -.1), (1, .1), (-1, .1)], (-.5, .5, -.5, .5))
        self.assertEqual(set(x for x, y in polygon), {-.5, .5})
        with self.assertRaisesRegex(ValueError, "too many periods"):
            periodic_centers(region(sx=100), 1, 1, (-.5, .5, -.5, .5))


class StructureFigureTests(unittest.TestCase):
    def setUp(self):
        self.layers = [["Air above", 0, "Air"], ["Device", .2, "Silicon"],
                       ["Spacer", .35, "Glass"], ["Substrate", 0, "Glass"]]
        self.patterns = [["circle", "Device", "Air", .49, 0, .12, 0, 0],
                         ["rectangle", "Spacer", "Air", 0, 0, .3, .15, 45]]

    def test_halfspace_positions_and_selected_highlight(self):
        stack, total, pad = layer_positions(self.layers, 1)
        self.assertAlmostEqual(total, .55)
        self.assertEqual((stack[0]["z0"], stack[0]["z1"]), (-pad, 0))
        self.assertEqual((stack[-1]["z0"], stack[-1]["z1"]), (total, total+pad))
        fig = build_structure_figure(self.layers, self.patterns, "Spacer", 1, 1)
        self.assertEqual(fig.layout.meta["selected_layer"], "Spacer")
        highlight = [s for s in fig.layout.shapes if s.type == "rect" and s.xref == "x2"]
        self.assertEqual(len(highlight), 1)
        self.assertAlmostEqual(highlight[0].y0, .2)
        self.assertAlmostEqual(highlight[0].y1, .55)
        self.assertLess(fig.layout.yaxis2.range[1], fig.layout.yaxis2.range[0])

    def test_gradio_pandas_and_records_match_without_mutation(self):
        frame = pd.DataFrame(self.layers, columns=LAYER_COLUMNS)
        original_frame = frame.copy(deep=True)
        original_patterns = copy.deepcopy(self.patterns)
        a = build_structure_figure(frame, self.patterns, "Device", 1, 1)
        b = build_structure_figure({"headers": list(LAYER_COLUMNS), "data": self.layers},
                                   {"headers": list(PATTERN_COLUMNS), "data": self.patterns}, "Device", 1, 1)
        c = build_structure_figure(frame.to_dict("records"),
                                   [dict(zip(PATTERN_COLUMNS, p)) for p in self.patterns], "Device", 1, 1)
        self.assertEqual(a.to_json(), b.to_json())
        self.assertEqual(a.to_json(), c.to_json())
        pd.testing.assert_frame_equal(frame, original_frame)
        self.assertEqual(self.patterns, original_patterns)

    def test_section_changes_when_cut_moves(self):
        a = build_structure_figure(self.layers, self.patterns, "Device", 1, 1, 1, 0)
        b = build_structure_figure(self.layers, self.patterns, "Device", 1, 1, 1, .2)
        def device_holes(fig):
            return [t for t in fig.data if t.xaxis == "x2" and t.text and "Device · circle" in t.text[0]]
        self.assertEqual(len(device_holes(a)), 1)
        self.assertEqual(len(device_holes(b)), 0)

    def test_periodically_equivalent_section_reports_input_and_display_cut(self):
        fig = build_structure_figure(self.layers, self.patterns, "Device", 1, 1, 3, 4.2)
        self.assertEqual(fig.layout.meta["cut_y_um"], 4.2)
        self.assertAlmostEqual(fig.layout.meta["display_cut_y_um"], .2)
        self.assertTrue(any("≡" in annotation.text for annotation in fig.layout.annotations))

    def test_hundred_layer_stack_is_complete_and_hoverable(self):
        layers = [["Top", 0, "Air"]] + [[f"Film {i}", .05, "Silicon" if i % 2 else "Glass"] for i in range(100)]
        layers.append(["Bottom", 0, "Glass"])
        patterns = [["circle", f"Film {i}", "Air", 0, 0, .1, 0, 0] for i in range(100)]
        fig = build_structure_figure(layers, patterns, "Film 77", .5, .5)
        self.assertEqual(fig.layout.meta["layer_count"], 102)
        self.assertEqual(fig.layout.meta["previewed_regions"], 100)
        self.assertAlmostEqual(fig.layout.meta["total_thickness_um"], 5)
        hover = [t for t in fig.data if t.name == "Layer details"][0]
        self.assertEqual(len(hover.y), 102)
        self.assertLess(len(fig.layout.annotations), 10)

    def test_invalid_transient_edits_are_annotated(self):
        for layers, ax in (([], 1), (self.layers, 0), (self.layers, float("nan")), ([self.layers[0]]*3, 1)):
            fig = build_structure_figure(layers, self.patterns, "Device", ax, 1)
            self.assertIn("error", fig.layout.meta)
            self.assertTrue(fig.layout.annotations)
        bad = copy.deepcopy(self.patterns)
        bad[0][5] = -1
        fig = build_structure_figure(self.layers, bad, "Device", 1, 1)
        self.assertEqual(fig.layout.meta["region_count"], 1)
        self.assertTrue(fig.layout.meta["warnings"])

    def test_air_colour_and_huge_region_do_not_crash(self):
        self.assertEqual(material_color("Air"), "#ffffff")
        self.assertEqual(material_color("Silicon"), material_color("Silicon"))
        self.assertNotEqual(material_color("Silicon"), material_color("Glass"))
        big = copy.deepcopy(self.patterns)
        big[0][5] = 100
        fig = build_structure_figure(self.layers, big, "Device", .5, .5, 100)
        self.assertEqual(fig.layout.meta["cells"], 7)
        self.assertTrue(fig.layout.meta["warnings"])


if __name__ == "__main__":
    unittest.main()
