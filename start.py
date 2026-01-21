#!/usr/bin/env python3
"""
Yazilign Bot System - Single Start Command

This script starts both the main bot and the registration bot simultaneously.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yazilign_bot_system import main

if __name__ == "__main__":
    main()