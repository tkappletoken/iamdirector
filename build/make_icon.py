from PIL import Image, ImageDraw, ImageFont

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
pad, r = 100, 185
d.rounded_rectangle([pad, pad, S - pad, S - pad], r, fill=(11, 11, 15, 255))
font = ImageFont.truetype("/System/Library/Fonts/STHeiti Medium.ttc", 520)
t = "導"
l, t0, rr, b = d.textbbox((0, 0), t, font=font)
d.text(((S - (rr - l)) / 2 - l, (S - (b - t0)) / 2 - t0), t, font=font, fill=(240, 240, 245, 255))
img.save("icon.png")
print("icon.png", img.size)
