#!/usr/bin/env python3

# This file was copied from toolbox-export in https://github.com/A6GibKm/silverblue-tools/

import tempfile
import os
import argparse
import subprocess
import sys

from xdg.Exceptions import ParsingError

try:
    from PIL import Image
    from xdg.DesktopEntry import DesktopEntry
    from xdg import BaseDirectory
    import xdg.IconTheme
except ImportError:
    sys.exit(
        'Could not find python dependencies, run "pip install -r requirements.txt"'
    )

# TODO separate in already installed and newly installed
# TODO Handle /opt
installed_paths = []


def already_installed(new_data: bytes, resource: str) -> bool:
    paths = filter(
        lambda d: (
            not d.startswith('/usr') and not d.startswith('/var/lib/flatpak')
        ),
        xdg.BaseDirectory.load_data_paths(resource),
    )

    for path in paths:
        for f in os.listdir(path):
            f_path = os.path.join(path, f)
            try:
                with open(f_path, 'br') as data:
                    old_data = data.read()
            except FileNotFoundError:
                continue
            if old_data == new_data:
                return True
    return False


def install(new_data: bytes, path: str, resource: str):
    home = os.environ.get('HOME')

    def r(path: str):
        return path.replace(home, '~')

    message_n = 'Already installed: {}'.format(r(path))
    message_y = 'Installed: {}'.format(r(path))

    if path in installed_paths:
        return
    if already_installed(new_data, resource):
        print(message_n)
        installed_paths.append(path)
        return

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(new_data)
        print(message_y)
        installed_paths.append(path)


def handle_pixmaps(pixmap: str, size: int):
    with Image.open(pixmap) as img:
        if size == 'scalable':
            resource = 'icons/hicolor/scalable/apps'
        else:
            resource = 'icons/hicolor/{}x{}/apps'.format(size, size)
        pixmap_size = img.size[0]
        ext = os.path.splitext(pixmap)[1]
        new_ext = '.png' if isinstance(size, int) else '.svg'
        pillow_ext = new_ext.replace('.', '').upper()
        icon_name = pixmap.split('/')[-1].replace(ext, new_ext)
        new_icon_path = os.path.join(
            BaseDirectory.save_data_path(resource), icon_name
        )
        if size == 'scalable':
            if ext == '.svg':
                img = img.resize((size, size))
            else:
                return
        elif pixmap_size % size == 0:
            if pixmap_size != size:
                img = img.resize((size, size))
        else:
            return

        with tempfile.NamedTemporaryFile() as tmp_f:
            img.save(tmp_f.name, pillow_ext)
            install(tmp_f.read(), new_icon_path, resource)


def copy_icon(app: str, size):
    if isinstance(size, int):
        icon_path = xdg.IconTheme.getIconPath(app, size=size)
    elif size == 'scalable':
        icon_path = xdg.IconTheme.getIconPath(app, extensions=['svg'])
    else:
        return

    if icon_path is None:
        return
    elif '/pixmaps/' in icon_path:
        handle_pixmaps(icon_path, size)
        return

    icon_file_name = os.path.basename(icon_path)
    if icon_path.startswith('/usr'):
        resource = icon_path.replace('/usr/local/share/', '')
        resource = resource.replace('/usr/share/', '')
    elif icon_path.startswith(BaseDirectory.save_data_path('')):
        resource = icon_path.replace(BaseDirectory.save_data_path(''), '')
    resource = resource.replace(icon_file_name, '')
    new_icon_path = os.path.join(
        BaseDirectory.save_data_path(resource), icon_file_name
    )

    try:
        with open(icon_path, 'br') as icon:
            install(icon.read(), new_icon_path, resource)
    except FileNotFoundError:
        pass


# Taken from https://github.com/takluyver/pyxdg/blob/master/xdg/Mime.py
def copy_mime(app: str):
    resource = os.path.join('mime', 'packages')
    paths = filter(
        lambda d: d.startswith('/usr'),
        xdg.BaseDirectory.load_data_paths(resource),
    )
    application = app + '.xml'
    for path in paths:
        file_path = os.path.join(path, application)
        new_file = os.path.join(
            BaseDirectory.save_data_path(resource), application
        )
        try:
            with open(file_path, 'br') as f:
                install(f.read(), new_file, resource)
        except FileNotFoundError:
            pass

        # Update the database...
        command = 'update-mime-database'
        if os.spawnlp(
            os.P_WAIT, command, command, BaseDirectory.save_data_path('mime')
        ):
            os.unlink(new_file)
            raise Exception(
                "The '%s' command returned an error code!\n"
                "Make sure you have the freedesktop.org shared MIME package:\n"
                "http://standards.freedesktop.org/shared-mime-info/" % command
            )


def copy_desktop_file(app: str, container: str | None) -> None:
    resource = 'applications'
    paths = filter(
        lambda d: d.startswith('/usr'),
        xdg.BaseDirectory.load_data_paths(resource),
    )
    application = app + '.desktop'
    for path in paths:
        file_path = os.path.join(path, application)
        try:
            desktop_file = DesktopEntry(file_path)
        except ParsingError:
            continue

        if not os.path.exists(file_path):
            continue

        exec_field = desktop_file.getExec()
        tryexec_field = desktop_file.getTryExec()

        container_arg = ''
        if container:
            container_arg = f'--container {container}'

        toolbox_cmds = ['toolbox', 'run', container_arg, exec_field]
        toolbox_cmd = ' '.join(filter(None, toolbox_cmds))

        if exec_field:
            desktop_file.set('Exec', toolbox_cmd)
        if tryexec_field:
            desktop_file.set('TryExec', 'toolbox')

        new_path = os.path.join(
            BaseDirectory.save_data_path(resource), application
        )

        with tempfile.NamedTemporaryFile() as tmp_f:
            desktop_file.write(tmp_f.name)
            install(tmp_f.read(), new_path, resource)
        command = [
            'flatpak-spawn',
            '--host',
            'update-desktop-database',
            BaseDirectory.save_data_path(resource),
        ]
        cmd_preview = ' '.join(command[2::])
        print(f'Running: {cmd_preview}')

        try:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            print('Failed to run', ' '.join(command))


def get_icon_name(app: str) -> str:
    application = app + '.desktop'
    resource = 'applications'

    paths = filter(
        lambda d: d.startswith('/usr'),
        xdg.BaseDirectory.load_data_paths(resource),
    )
    for path in paths:
        file_path = os.path.join(path, application)
        if not os.path.exists(file_path):
            continue
        desktop_file = DesktopEntry(file_path)
        icon = desktop_file.getIcon()
        return icon


def copy_metadata(app: str):
    resource = 'metainfo'
    for info_dir in ['appdata', 'metainfo']:
        xml_dir = os.path.join('/usr/share', info_dir)
        for app_ext in ['.appdata.xml', '.metainfo.xml']:
            application = app + app_ext
            metadata_path = os.path.join(xml_dir, application)
            new_metadata_path = os.path.join(
                BaseDirectory.save_data_path(resource), application
            )
            try:
                with open(metadata_path, 'br') as f:
                    f_contents = f.read()
                    install(f_contents, new_metadata_path, resource)
            except FileNotFoundError:
                pass


def list_desktop_files():
    paths = filter(
        lambda d: d.startswith('/usr'),
        xdg.BaseDirectory.load_data_paths('applications'),
    )
    for desktop_dir in paths:
        if desktop_dir.startswith('/usr'):
            L = [
                os.path.splitext(f)[0]
                for f in os.listdir(desktop_dir)
                if os.path.splitext(f)[1] == '.desktop'
            ]
            for l in L:
                print(l)


def main():

    # if not os.path.exists('/README.md'):
    if os.environ.get('TOOLBOX_PATH') is None:
        exit('Not inside a toolbox container')

    parser = argparse.ArgumentParser()
    parser.add_argument('application', help='application to export', nargs='?')
    parser.add_argument(
        '--list',
        action='store_true',
        help='list desktop files inside the toolbox',
    )
    parser.add_argument(
        '-c',
        '--container',
        type=str,
        help='name of the toolbox container',
    )
    opts = parser.parse_args()

    if opts.list:
        list_desktop_files()
        sys.exit()

    if not opts.application:
        sys.exit(
            'Specify an application. See --help for additional information'
        )

    sizes = [16, 24, 32, 48, 64, 96, 128, 256, 512, 'scalable']
    app = opts.application
    copy_desktop_file(app, opts.container)
    app_icon = get_icon_name(app)
    for size in sizes:
        copy_icon(app_icon, size)
    copy_mime(app)
    copy_metadata(app)


if __name__ == "__main__":
    main()
