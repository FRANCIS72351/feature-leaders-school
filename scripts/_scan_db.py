import struct, os
db = r"c:\Users\Francis\Desktop\essential\SCHOOL_MANAGEMENT\instance\keeptrack_full.db"
with open(db, "rb") as f:
    header = f.read(100)
print("magic", header[:16])
print("page size", struct.unpack(">H", header[16:18])[0])
# search for attendance string occurrences
with open(db, "rb") as f:
    data = f.read()
idx = 0
count = 0
while True:
    i = data.find(b"attendance", idx)
    if i < 0: break
    count += 1
    snippet = data[max(0,i-40):i+80]
    print(f"--- hit {count} at {i} ---")
    print(snippet)
    idx = i + 1
print("total hits", count)
