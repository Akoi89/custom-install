import sys
from os.path import dirname, abspath

# make "import custominstall" work when pytest is started from somewhere else
sys.path.insert(0, dirname(dirname(abspath(__file__))))
