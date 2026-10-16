"""真实 CZML 的 UTC 历元回归；显式启用可选 Orekit 环境才运行。"""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

@unittest.skipUnless(os.environ.get("EOS_RUN_OREKIT_TESTS") == "1",
                     "opt-in: EOS_RUN_OREKIT_TESTS=1")
class OrbitExportIntegrationTests(unittest.TestCase):
    def test_equivalent_orbit_and_scene_offsets_export_identical_czml(self):
        # 所有输入/轨道包副本都在 TemporaryDirectory，退出后立即清理。
        from draw.orekit_to_czml import demo
        from test_window_recompute import fixture
        project=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="eos-orbit-export-test-") as directory:
            root=Path(directory)
            data=root/"orekit-data.zip"
            shutil.copyfile(project/"utils/orekit-data.zip",data)
            scene=fixture()
            scene["metadata"].update(duration=60,time_step=30)
            outputs=[]
            for index,(epoch,creation) in enumerate((
                ("18 Nov 2025 12:00:00.000","2025-11-18T12:00:00Z"),
                ("2025-11-18T12:00:00Z","2025-11-18T20:00:00+08:00"),
                ("2025-11-18T20:00:00+08:00","2025-11-18T07:00:00-05:00")
            )):
                scene["satellites"][0]["orbital_params"]["epoch"]=epoch
                scene["metadata"]["creation_time"]=creation
                source=root/f"input-{index}.json"
                output=root/f"orbit-{index}.czml"
                source.write_text(json.dumps(scene),encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()):
                    demo(str(source),str(output),str(data),orbit_step_s=30)
                outputs.append(json.loads(output.read_text()))
            self.assertEqual(outputs[0],outputs[1])
            self.assertEqual(outputs[0],outputs[2])
            self.assertTrue(outputs[0][0]["clock"]["interval"].startswith("2025-11-18T12:00:00"))
            orbit=next(row for row in outputs[0] if row["id"]=="s1")
            self.assertEqual(len(orbit["position"]["cartographicDegrees"]),12)
