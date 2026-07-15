import unittest

from geofvbridge.gui.reports import format_fe_inspection, format_tough_report


class GuiReportTests(unittest.TestCase):
    def test_fe_report_is_human_readable_in_both_languages(self):
        inspection = {
            "path": "case.msh",
            "dimension": 2,
            "points": 4,
            "cell_types": {"quad": 1},
            "physical_groups": {"ROCK": {"dimension": 2, "tag": 1}},
            "coordinate_bounds": {"x": [0.0, 1.0], "y": [0.0, 0.0], "z": [0.0, 1.0]},
        }
        chinese = format_fe_inspection(inspection, "zh_CN")
        english = format_fe_inspection(inspection, "en_US")
        self.assertIn("网格概况", chinese)
        self.assertIn("Mesh overview", english)
        self.assertIn("ROCK", chinese)
        self.assertNotIn('"cell_types"', chinese)

    def test_tough_report_hides_ordinary_cell_label_mapping(self):
        manifest = {
            "backend": "TOUGH2/ECO2M",
            "cells": 2,
            "connections": 1,
            "cell_labels": {"0": "A0000", "1": "A0001"},
            "materials": {"Rock": "ROCK"},
            "boundary_cells": [],
            "inactive_cells": [],
            "generated_boundary_cells": [],
            "files": {
                "mesh": "MESH",
                "cell_map": "cell_map.csv",
                "manifest": "mesh_manifest.json",
            },
        }
        report = format_tough_report(manifest, "en_US")
        self.assertIn("Cell-label mappings: 2", report)
        self.assertIn("cell_map.csv", report)
        self.assertNotIn("A0000", report)
        self.assertNotIn("A0001", report)
        self.assertNotIn('"cell_labels"', report)


if __name__ == "__main__":
    unittest.main()
