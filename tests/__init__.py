import os
import unittest

# tests that take tens of seconds (soundbank rendering, every patch subset); run them with NUXDSP_SLOW=1
# before a commit that touches the soundbank, the web page or the layout of patches
slow = unittest.skipUnless(os.environ.get("NUXDSP_SLOW"), "slow, set NUXDSP_SLOW=1")
