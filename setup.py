from setuptools import setup

setup(name='pyalarmdotcom',
      version='0.0.3',
      description='Library to interface with alarm.com accounts',
      url='http://github.com/Xorso/pyalarmdotcom',
      author='Daren Lord',
      author_email='lord.daren@gmail.com',
      license='MIT',
      packages=['pyalarmdotcom'],
      install_requires=[
        "selenium",
	  ],
      zip_safe=True)
