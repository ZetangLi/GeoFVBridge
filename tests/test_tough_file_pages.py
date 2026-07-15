import tempfile
import unittest
from pathlib import Path

import numpy as np

from geofvbridge.core.incon import compute_initial_conditions
from geofvbridge.core.inp import (
    get_default_multi,
    get_default_param,
    get_default_rock,
    get_default_selec,
    write_flow_inp,
)


class ToughFilePageTests(unittest.TestCase):
    def test_param_record_writes_mop_15_and_16_in_their_fixed_columns(self):
        param = get_default_param()
        mop = [0] * 24
        mop[14] = 1
        mop[15] = 4
        param["mop_vals"] = mop

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "flow.inp"
            write_flow_inp(
                path,
                [get_default_rock("ROCK")],
                param,
                [],
                "",
                get_default_multi(),
                get_default_selec(),
            )
            lines = path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(lines[0], "")
        self.assertTrue(lines[1].startswith("ROCKS"))
        param_header = next(index for index, line in enumerate(lines) if line.startswith("PARAM"))
        mop_record = lines[param_header + 1][16:40]
        self.assertEqual(len(mop_record), 24)
        self.assertEqual(mop_record[14], "1")
        self.assertEqual(mop_record[15], "4")

    def test_incon_profiles_always_use_z_coordinates(self):
        centers = np.array(
            [
                [0.0, 0.0, 10.0],
                [1000.0, -500.0, 10.0],
                [0.0, 0.0, 0.0],
            ]
        )
        values = compute_initial_conditions(
            centers,
            z_top=10.0,
            z_bot=0.0,
            p_top=100.0,
            p_bot=200.0,
            t_top=20.0,
            t_bot=30.0,
        )

        np.testing.assert_allclose(values[0], values[1])
        self.assertEqual(values[0, 0], 100.0)
        self.assertEqual(values[2, 0], 200.0)
        self.assertEqual(values[0, 3], 20.0)
        self.assertEqual(values[2, 3], 30.0)


if __name__ == "__main__":
    unittest.main()
