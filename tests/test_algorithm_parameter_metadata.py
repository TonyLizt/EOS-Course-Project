"""All actual registered algorithms, without running any scheduling algorithm."""
import json
from pathlib import Path
import subprocess
import unittest

from eos_system import algorithm_registry as registry
from eos_system.algorithm_presentation import algorithm_info


ROOT = Path(__file__).resolve().parents[1]


def without_presentation(value):
    if isinstance(value, dict):
        return {key: without_presentation(item) for key, item in value.items()
                if key not in {'title', 'description'}}
    if isinstance(value, list):
        return [without_presentation(item) for item in value]
    return value


class ParameterMetadataTests(unittest.TestCase):
    def test_all_registered_metadata_and_validation_contracts_unchanged(self):
        self.assertEqual(set(registry._SPECS), set(registry.COMPARISON_ALGORITHMS)
                         | {item['model_id'] for item in registry.list_schedule_models()})
        for aid, spec in registry._SPECS.items():
            with self.subTest(algorithm=aid):
                info = algorithm_info(spec)
                self.assertTrue(all(info[k] for k in ('name', 'description', 'strategy', 'objectives', 'limitations')))
                schema = info['parameters']
                self.assertEqual(without_presentation(schema), without_presentation(spec.params_model.model_json_schema()))
                for key, prop in schema.get('properties', {}).items():
                    self.assertTrue(prop.get('description'), (aid, key))
                    self.assertNotEqual(prop['title'], key)
                self.assertEqual(spec.parse_params({}).model_dump(), spec.params_model().model_dump())
                with self.assertRaises(ValueError):
                    spec.parse_params({'unknown_parameter': 1})

    def test_actual_registry_schemas_render_and_validate_in_javascript(self):
        catalog = [algorithm_info(spec) for spec in registry._SPECS.values()]
        script = r'''
const assert=require('node:assert/strict');
const P=require('./eos_system/web/algorithm-parameters.js');
const UI=require('./eos_system/web/experiment-ui.js');
const rows=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
for(const a of rows){
 assert.deepEqual(P.validate(a.parameters,{}),[],a.algorithm_id);
 assert.ok(!P.render(a).includes('additionalProperties'),a.algorithm_id);
 assert.ok(!UI.description(a).includes('anyOf'),a.algorithm_id);
 for(const key of Object.keys(a.parameters.properties))assert.ok(P.render(a).includes('data-key="'+key+'"'));
 assert.ok(P.validate(a.parameters,{unknown_parameter:1}).length,a.algorithm_id);
}
console.log(rows.length+' registry schemas passed');
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, input=json.dumps(catalog),
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'{len(catalog)} registry schemas passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
