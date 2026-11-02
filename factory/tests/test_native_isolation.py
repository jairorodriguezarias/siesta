"""Optional offline integration with Pi's real prompt resource loader."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pipeline.pi import build_args


LOADER_CHECK = r"""
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
const input = JSON.parse(readFileSync(0, 'utf8'));
const moduleAt = path => import(pathToFileURL(join(input.package, path)).href);
const {DefaultResourceLoader} = await moduleAt('dist/core/resource-loader.js');
const {SettingsManager} = await moduleAt('dist/core/settings-manager.js');
const {parseArgs} = await moduleAt('dist/cli/args.js');
const parsed = parseArgs(input.args);
const loader = new DefaultResourceLoader({
    cwd: input.project,
    agentDir: input.profile,
    settingsManager: SettingsManager.inMemory({}, {
        projectTrusted: parsed.projectTrustOverride ?? true,
    }),
    noContextFiles: parsed.noContextFiles,
    noExtensions: parsed.noExtensions,
    noSkills: parsed.noSkills,
    noPromptTemplates: parsed.noPromptTemplates,
    noThemes: true,
    systemPrompt: parsed.systemPrompt,
    appendSystemPrompt: parsed.appendSystemPrompt,
});
await loader.reload();
console.log(JSON.stringify({
    system: loader.getSystemPrompt(), append: loader.getAppendSystemPrompt(),
}));
"""


class NativeIsolation(unittest.TestCase):
    def test_isolated_review_excludes_global_and_project_system_files(self):
        pi, node = shutil.which('pi'), shutil.which('node')
        if not pi or not node:
            self.skipTest('Native isolation check needs installed Pi and Node')
        package = next((parent for parent in Path(pi).resolve().parents
                        if (parent / 'dist/core/resource-loader.js').is_file()), None)
        if package is None:
            self.skipTest('Installed Pi does not expose its resource-loader module')
        args = build_args('consultant', 'Review the supplied design.', 'Return JSON.',
                          tools='no', isolated=True)[1:]
        for scope in ('global', 'project'):
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                project, profile = root / 'project', root / 'profile'
                project.mkdir()
                profile.mkdir()
                folder = profile if scope == 'global' else project / '.pi'
                folder.mkdir(exist_ok=True)
                (folder / 'SYSTEM.md').write_text('INHERITED_SYSTEM_SENTINEL')
                (folder / 'APPEND_SYSTEM.md').write_text('INHERITED_APPEND_SENTINEL')
                proc = subprocess.run(
                    [node, '--input-type=module', '-e', LOADER_CHECK],
                    input=json.dumps({'package': str(package), 'project': str(project),
                                      'profile': str(profile), 'args': args}),
                    capture_output=True, text=True, timeout=20)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                prompts = json.loads(proc.stdout)
                self.assertNotIn('INHERITED_', json.dumps(prompts))
                self.assertEqual(prompts['append'], [])
