"""say_to.py OUT.wav RATE TEXT... : synthesize speech (macOS say) to a 16 kHz mono WAV; prints its duration."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pc
audio, secs = pc.speak_to_wav(" ".join(sys.argv[3:]), int(sys.argv[2]))
tmp = sys.argv[1] + ".tmp"
open(tmp, "wb").write(audio); os.replace(tmp, sys.argv[1])
print(f"{secs:.1f}s {len(audio)} bytes")
