"""從 stdin 讀 Python 原始碼，剪掉註解與 docstring（程式原字不動），寫到 stdout。切完能 parse 才輸出。"""
import ast, io, re, sys, tokenize

src = sys.stdin.read()
# 只用 \n 分行：str.splitlines 會把 \u2028、\x0c 之類也當換行，跟 ast／tokenize 的行號對不上
lines = [l + "\n" for l in src.split("\n")]
lines[-1] = lines[-1][:-1]
offs = [0]
for l in lines:
    offs.append(offs[-1] + len(l))
pos = lambda r, c: offs[r - 1] + c
# ast 的 col_offset 是 UTF-8 位元組數（tokenize 是字元數）：中文一行就差很多
bpos = lambda r, c: offs[r - 1] + len(lines[r - 1].encode('utf-8')[:c].decode('utf-8', 'ignore'))

ranges = []                       # [start, end, replacement]
for t in tokenize.generate_tokens(io.StringIO(src).readline):
    if t.type == tokenize.COMMENT:
        ranges.append([pos(*t.start), pos(*t.end), ""])
for node in ast.walk(ast.parse(src)):
    if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        b = node.body
        if b and isinstance(b[0], ast.Expr) and isinstance(getattr(b[0], "value", None), ast.Constant) \
                and isinstance(b[0].value.value, str):
            d = b[0]
            ranges.append([bpos(d.lineno, d.col_offset), bpos(d.end_lineno, d.end_col_offset),
                           "pass" if len(b) == 1 else ""])

ranges.sort()
out, p = [], 0
for s, e, rep in ranges:
    if s < p:
        continue
    ls = src.rfind("\n", 0, s) + 1
    le = src.find("\n", e)
    le = len(src) if le < 0 else le
    if rep:
        out.append(src[p:s] + rep)
        p = e
        continue
    if not src[ls:s].strip() and not src[e:le].strip():
        s, e = ls, (le + 1 if le < len(src) else le)        # 整行
    else:
        while s > ls and src[s - 1] in " \t":                 # 行尾的空白一起拿掉
            s -= 1
    out.append(src[p:s])
    p = e
res = re.sub(r"\n{3,}", "\n\n", "".join(out) + src[p:])
ast.parse(res)
sys.stdout.write(res)
