import argparse
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "export_lambda"))

import render

class DirS3:

    def __init__(self, root):
        self.root = os.path.abspath(root)

    def path(self, bucket, key):
        if not render.BUCKET.match(bucket or "") or ".." in key.split("/") or key.startswith("/"):
            raise render.RenderError("bucket 或 key 不合法：%r %r" % (bucket, key))
        p = os.path.abspath(os.path.join(self.root, bucket, key))
        if not p.startswith(os.path.join(self.root, bucket) + os.sep):
            raise render.RenderError("key 跳出了 bucket：%r" % key)
        return p

    def fetch(self, bucket, key, dst):
        src = self.path(bucket, key)
        if not os.path.exists(src):
            raise render.RenderError("S3 沒有這個物件：s3://%s/%s" % (bucket, key))
        shutil.copyfile(src, dst)

    def put(self, bucket, key, src, ctype):
        dst = self.path(bucket, key)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if isinstance(src, (bytes, bytearray)):
            with open(dst, "wb") as f:
                f.write(src)
        else:
            shutil.copyfile(src, dst)

def run(spec, s3_root, work=None, strict=False, ffmpeg=None, ffprobe=None, fontsdir=None, container="mp4"):
    s3 = DirS3(s3_root)

    def status(d):
        u, i, b = spec.get("user"), spec.get("id"), spec.get("out_bucket")
        if isinstance(u, str) and render.USER.match(u) and isinstance(i, str) and render.ID.match(i) \
                and isinstance(b, str) and render.BUCKET.match(b):
            s3.put(b, render.out_keys(u, i)["status"], json.dumps(d, ensure_ascii=False).encode(), "application/json")

    own = work is None
    work = work or tempfile.mkdtemp(prefix="export-local-")
    try:
        return render.run(spec, s3.fetch, s3.put, work, ffmpeg=ffmpeg, ffprobe=ffprobe,
                          strict=strict, status=status, fontsdir=fontsdir, container=container)
    finally:
        if own:
            shutil.rmtree(work, ignore_errors=True)

def main(argv=None):
    ap = argparse.ArgumentParser(description="本機匯出時間軸 mp4（假的 S3）")
    ap.add_argument("spec")
    ap.add_argument("--s3", required=True, help="假的 S3 根目錄")
    ap.add_argument("--work", help="暫存目錄（預設用完就刪）")
    ap.add_argument("--strict", action="store_true", help="跟 Lambda 一樣：沒有 libass 就失敗")
    a = ap.parse_args(argv)
    with open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)
    st = run(spec, a.s3, a.work, a.strict)
    print(json.dumps(st, ensure_ascii=False, indent=2))
    return 0 if st.get("state") == "done" else 1

if __name__ == "__main__":
    sys.exit(main())
