package com.kards.engine;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 极简 JSON 解析器（只读）。Android 与 CLI 共用，零依赖。
 *  映射：object→LinkedHashMap&lt;String,Object&gt;，array→ArrayList&lt;Object&gt;，
 *  number→Double（整数场景用 {@link #getInt} 取整）。 */
public final class MiniJson {
    private final String s;
    private int i;

    private MiniJson(String s) { this.s = s; }

    public static Object parse(String text) {
        return new MiniJson(text).parseValue();
    }

    private Object parseValue() {
        skipWs();
        char c = s.charAt(i);
        switch (c) {
            case '{': return parseObject();
            case '[': return parseArray();
            case '"': return parseString();
            case 't': expect("true"); return Boolean.TRUE;
            case 'f': expect("false"); return Boolean.FALSE;
            case 'n': expect("null"); return null;
            default: return parseNumber();
        }
    }

    private Map<String, Object> parseObject() {
        Map<String, Object> m = new LinkedHashMap<>();
        i++; // {
        skipWs();
        if (s.charAt(i) == '}') { i++; return m; }
        while (true) {
            skipWs();
            String key = parseString();
            skipWs();
            expect(":");
            i++; // :
            m.put(key, parseValue());
            skipWs();
            char c = s.charAt(i);
            if (c == ',') { i++; continue; }
            if (c == '}') { i++; return m; }
            throw err("期望 , 或 }");
        }
    }

    private List<Object> parseArray() {
        List<Object> l = new ArrayList<>();
        i++; // [
        skipWs();
        if (s.charAt(i) == ']') { i++; return l; }
        while (true) {
            l.add(parseValue());
            skipWs();
            char c = s.charAt(i);
            if (c == ',') { i++; continue; }
            if (c == ']') { i++; return l; }
            throw err("期望 , 或 ]");
        }
    }

    private String parseString() {
        StringBuilder sb = new StringBuilder();
        i++; // "
        while (true) {
            char c = s.charAt(i++);
            if (c == '"') return sb.toString();
            if (c == '\\') {
                char e = s.charAt(i++);
                switch (e) {
                    case 'n': sb.append('\n'); break;
                    case 't': sb.append('\t'); break;
                    case 'r': sb.append('\r'); break;
                    case 'b': sb.append('\b'); break;
                    case 'f': sb.append('\f'); break;
                    case 'u':
                        sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16));
                        i += 4;
                        break;
                    default: sb.append(e);
                }
            } else {
                sb.append(c);
            }
        }
    }

    private Object parseNumber() {
        int start = i;
        while (i < s.length() && "-+.eE0123456789".indexOf(s.charAt(i)) >= 0) i++;
        return Double.parseDouble(s.substring(start, i));
    }

    private void skipWs() {
        while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++;
    }

    private void expect(String lit) {
        if (!s.startsWith(lit, i)) throw err("期望 " + lit);
        i += lit.length();
    }

    private IllegalArgumentException err(String msg) {
        return new IllegalArgumentException("JSON 解析错误 @" + i + ": " + msg);
    }

    // ---- 便捷取值 ----
    public static String str(Map<String, Object> m, String key) {
        Object v = m.get(key);
        return v == null ? "" : String.valueOf(v);
    }

    public static int getInt(Map<String, Object> m, String key) {
        Object v = m.get(key);
        if (v instanceof Double) return (int) Math.round((Double) v);
        if (v instanceof Number) return ((Number) v).intValue();
        return 0;
    }

    @SuppressWarnings("unchecked")
    public static List<Object> arr(Object v) {
        return v == null ? new ArrayList<>() : (List<Object>) v;
    }

    @SuppressWarnings("unchecked")
    public static Map<String, Object> obj(Object v) {
        return v == null ? new LinkedHashMap<>() : (Map<String, Object>) v;
    }

    public static boolean bool(Object v) { return Boolean.TRUE.equals(v); }
}
