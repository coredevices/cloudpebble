import os
import sys

# The controller's modules are scripts beside each other, not a package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
