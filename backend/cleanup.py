import os
for f in ['test_import.py', 'test_import2.py']:
    try:
        os.remove(f)
        print(f'Removed {f}')
    except FileNotFoundError:
        pass
