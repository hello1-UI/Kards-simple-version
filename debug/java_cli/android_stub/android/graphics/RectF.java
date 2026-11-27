package android.graphics;

public class RectF {
    public float left, top, right, bottom;
    public RectF() { }
    public RectF(float l, float t, float r, float b) {
        left = l; top = t; right = r; bottom = b;
    }
    public boolean contains(float x, float y) {
        return x >= left && x <= right && y >= top && y <= bottom;
    }
    public float width() { return right - left; }
    public float height() { return bottom - top; }
    public float centerX() { return (left + right) / 2f; }
    public float centerY() { return (top + bottom) / 2f; }
}
