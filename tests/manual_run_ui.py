"""Manual create to avoid WorkBuddy file lock"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

print("Test script is working!")
print("Python path:")
for p in sys.path[:3]:
    print("  - " + str(p))
