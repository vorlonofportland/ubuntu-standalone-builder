import base64

import py
import pytest
import yaml
from six.moves.urllib.parse import urlparse

import generate_build_config


class TestGetPPASnippet(object):

    def test_unknown_url(self):
        with pytest.raises(ValueError):
            generate_build_config._get_ppa_snippet('ftp://blah')

    def test_public_ppa(self):
        result = generate_build_config._get_ppa_snippet('ppa:foo/bar')
        expected = '- chroot $CHROOT_ROOT add-apt-repository -y -u ppa:foo/bar'
        assert result == expected

    def test_https_not_private_ppa(self):
        with pytest.raises(ValueError):
            generate_build_config._get_ppa_snippet('https://blah')

    def test_private_ppa_no_key(self):
        with pytest.raises(ValueError):
            generate_build_config._get_ppa_snippet(
                'https://private-ppa.example.com')

    def test_private_ppa_with_key(self):
        result = generate_build_config._get_ppa_snippet(
            'https://private-ppa.example.com', 'DEADBEEF')
        assert 'apt-get install -y apt-transport-https' in result
        assert 'deb https://private-ppa.example.com xenial main' in result
        assert ('apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 '
                '--recv-keys DEADBEEF' in result)


class TestWriteCloudConfig(object):

    def test_writes_to_file(self, tmpdir):
        output_file = tmpdir.join('output.yaml')
        generate_build_config._write_cloud_config(output_file.strpath)
        assert output_file.check()

    def test_written_output_is_yaml(self, tmpdir):
        output_file = tmpdir.join('output.yaml')
        generate_build_config._write_cloud_config(output_file.strpath)
        yaml.load(output_file.read())

    def test_written_output_is_cloud_config(self, tmpdir):
        output_file = tmpdir.join('output.yaml')
        generate_build_config._write_cloud_config(output_file.strpath)
        assert '#cloud-config' == output_file.readlines(cr=False)[0].strip()

    def test_default_build_id_is_output(self, tmpdir):
        output_file = tmpdir.join('output.yaml')
        generate_build_config._write_cloud_config(output_file.strpath)
        assert '- export BUILD_ID=output\n' in output_file.readlines()

    def test_write_files_not_included_by_default(self, tmpdir):
        output_file = tmpdir.join('output.yaml')
        generate_build_config._write_cloud_config(output_file.strpath)
        cloud_config = yaml.load(output_file.open())
        assert 'write_files' not in cloud_config

    def test_no_ppa_included_by_default(self, tmpdir):
        output_file = tmpdir.join('output.yaml')
        generate_build_config._write_cloud_config(output_file.strpath)
        assert 'add-apt-repository' not in output_file.read()
        assert 'apt-transport-https' not in output_file.read()

    def _get_wget_line(self, output_file):
        wget_lines = [ln for ln in output_file.readlines() if 'wget' in ln]
        assert 1 == len(wget_lines)
        return wget_lines[0]

    def test_daily_image_used(self, tmpdir):
        output_file = tmpdir.join('output.yaml')
        generate_build_config._write_cloud_config(output_file.strpath)
        wget_line = self._get_wget_line(output_file)
        assert 'xenial-server-cloudimg-amd64-root.tar.xz ' in wget_line

    def test_latest_daily_image_used(self, tmpdir):
        output_file = tmpdir.join('output.yaml')
        generate_build_config._write_cloud_config(output_file.strpath)
        url = self._get_wget_line(output_file).split()[2]
        path = urlparse(url).path
        assert 'current' == path.split('/')[2]

    def test_ppa_snippet_included(self, tmpdir):
        output_file = tmpdir.join('output.yaml')
        generate_build_config._write_cloud_config(
            output_file.strpath, ppa='ppa:foo/bar')
        assert 'add-apt-repository -y -u ppa:foo/bar' in output_file.read()


def customisation_script_combinations():
    customisation_script_content = '#!/bin/sh\nchroot'
    binary_customisation_script_content = '#!/bin/sh\nbinary'
    return [
        {'customisation_script': customisation_script_content},
        {'binary_customisation_script': binary_customisation_script_content},
        {'customisation_script': customisation_script_content,
         'binary_customisation_script': binary_customisation_script_content},
    ]


class TestWriteCloudConfigWithCustomisationScript(object):

    @pytest.fixture(autouse=True, params=customisation_script_combinations())
    def customisation_script_tmpdir(self, request, tmpdir):
        self.output_file = tmpdir.join('output.yaml')
        self.kwargs = {}
        self.test_config = {}
        for script in request.param:
            script_file = tmpdir.join(script + '.sh')
            script_file.write(request.param[script])
            self.kwargs[script] = script_file.strpath
            self.test_config[script] = {'script_file': script_file,
                                        'content': request.param[script]}

    def test_single_write_files_stanza_produced_for_customisation_script(self):
        generate_build_config._write_cloud_config(
            self.output_file.strpath, **self.kwargs)
        cloud_config = yaml.load(self.output_file.open())
        assert len(self.kwargs) == len(cloud_config['write_files'])

    def test_customisation_script_owned_by_root(self):
        generate_build_config._write_cloud_config(
            self.output_file.strpath, **self.kwargs)
        cloud_config = yaml.load(self.output_file.open())
        for stanza in cloud_config['write_files']:
            assert 'root:root' == stanza['owner']

    def test_customisation_script_is_executable_by_root(self):
        generate_build_config._write_cloud_config(
            self.output_file.strpath, **self.kwargs)
        cloud_config = yaml.load(self.output_file.open())
        for stanza in cloud_config['write_files']:
            assert '7' == stanza['permissions'][1]

    def test_customisation_script_placed_in_correct_directory(self):
        generate_build_config._write_cloud_config(
            self.output_file.strpath, **self.kwargs)
        cloud_config = yaml.load(self.output_file.open())
        for stanza in cloud_config['write_files']:
            path = py.path.local(stanza['path'])
            assert ('/home/ubuntu/build-output/chroot-autobuild'
                    '/usr/share/livecd-rootfs/live-build/ubuntu-cpc/hooks' ==
                    path.dirname)

    def test_customisation_script_is_an_appropriate_hook(self):
        generate_build_config._write_cloud_config(
            self.output_file.strpath, **self.kwargs)
        cloud_config = yaml.load(self.output_file.open())
        for stanza in cloud_config['write_files']:
            path = py.path.local(stanza['path'])
            if 'chroot' in base64.b64decode(stanza['content']).decode('utf-8'):
                assert '.chroot' == path.ext
            else:
                assert '.binary' == path.ext

    def test_customisation_script_marked_as_base64(self):
        generate_build_config._write_cloud_config(
            self.output_file.strpath, **self.kwargs)
        cloud_config = yaml.load(self.output_file.open())
        for stanza in cloud_config['write_files']:
            assert 'b64' == stanza['encoding']

    def test_customisation_script_is_included_in_template_as_base64(self):
        generate_build_config._write_cloud_config(
            self.output_file.strpath, **self.kwargs)
        cloud_config = yaml.load(self.output_file.open())
        for stanza in cloud_config['write_files']:
            if stanza['path'].endswith('chroot'):
                expected_content = self.test_config[
                    'customisation_script']['content']
            else:
                expected_content = self.test_config[
                    'binary_customisation_script']['content']
            assert expected_content == base64.b64decode(
                stanza['content']).decode('utf-8')

    def test_empty_customisation_script_doesnt_produce_write_files_stanza(
            self):
        for test_config in self.test_config.values():
            test_config['script_file'].remove()
            test_config['script_file'].ensure()
        generate_build_config._write_cloud_config(
            self.output_file.strpath, **self.kwargs)
        cloud_config = yaml.load(self.output_file.open())
        assert 'write_files' not in cloud_config


class TestMain(object):

    def test_main_exits_nonzero_with_no_cli_arguments(self, mocker):
        mocker.patch('sys.argv', ['ubuntu-standalone-builder.py'])
        with pytest.raises(SystemExit) as excinfo:
            generate_build_config.main()
        assert excinfo.value.code > 0

    def test_main_exits_nonzero_with_too_many_cli_arguments(self, mocker):
        mocker.patch(
            'sys.argv', ['ubuntu-standalone-builder.py', '1', '2', '3'])
        with pytest.raises(SystemExit) as excinfo:
            generate_build_config.main()
        assert excinfo.value.code > 0

    def test_main_passes_arguments_to_write_cloud_config(self, mocker):
        output_filename = 'output.yaml'
        binary_customisation_script = 'binary.sh'
        customisation_script = 'script.sh'
        ppa = 'ppa:foo/bar'
        ppa_key = 'DEADBEEF'
        mocker.patch('sys.argv', ['ubuntu-standalone-builder.py',
                                  output_filename,
                                  '--binary-customisation-script',
                                  binary_customisation_script,
                                  '--customisation-script',
                                  customisation_script, '--ppa', ppa,
                                  '--ppa-key', ppa_key])
        write_cloud_config_mock = mocker.patch(
            'generate_build_config._write_cloud_config')
        generate_build_config.main()
        assert [mocker.call(
            output_filename,
            binary_customisation_script=binary_customisation_script,
            customisation_script=customisation_script,
            ppa=ppa,
            ppa_key=ppa_key)] == write_cloud_config_mock.call_args_list
