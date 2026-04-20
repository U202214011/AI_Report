try:
    from flask import Flask
    print("Flask is available")
except ImportError:
    print("Flask is not available")
