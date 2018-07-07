from setuptools import setup, find_packages


if __name__ == '__main__':
    setup(
        name='suggestive2',
        version='0.1.0',
        description='Python MPD client with integrated Last.FM support',
        author='Scott Kruger',
        author_email='scott@chojin.org',
        url='https://github.com/thesquelched/suggestive2',
        keywords='suggestive mpd lastfm music',

        packages=find_packages(
            exclude='tests',
        ),
        entry_points={
            'console_scripts': [
                'suggestive2 = suggestive2.app:main',
            ],
        },

        package_data={
            'suggestive2': [
                'alembic/env.py',
                'alembic/script.py.mako',
                'alembic/versions/*.py'
            ],
        },
        install_requires=[
            'urwid >= 2.0.1',
            'python-mpd2 < 2.0.0',
        ],
    )
