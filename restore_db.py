import base64
import tarfile
import os

print("🔄 Restoring database from encoded file...")

# Read encoded database
with open('db_base64.txt', 'r') as f:
    db_encoded = f.read()

# Decode
print("📦 Decoding database...")
with open('db.tar.gz', 'wb') as f:
    f.write(base64.b64decode(db_encoded))

# Extract
print("📂 Extracting database...")
with tarfile.open('db.tar.gz', 'r:gz') as tar:
    tar.extractall()

# Cleanup
os.remove('db.tar.gz')

# Verify
if os.path.exists('pro4kings.db'):
    size = os.path.getsize('pro4kings.db') / (1024 * 1024)
    print(f"✅ Database restored successfully! Size: {size:.2f} MB")
else:
    print("❌ Database restore failed!")
