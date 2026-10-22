// DeskIsle liquid glass.  One pass draws: soft drop shadow, the glass body
// (refracted + blurred wallpaper sampled in monitor space), tone/tint, a
// specular rim and fine grain.  Output is premultiplied alpha.
//
// The edge refraction model (sampling the backdrop further inside the shape
// the closer a pixel is to the rim, plus a slight chromatic split) follows
// the idea of OverShifted/LiquidGlass (MIT, Copyright (c) 2026 Sepehr Kalanaki);
// the rounded-superellipse distance field works for any aspect ratio.
#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 itemSize;   // px of this effect item (body + shadow padding)
    float pad;       // shadow padding on every side (px)
    float radius;    // corner radius of the body (px)
    float exponent;  // corner superellipse exponent (2 = circular, ~3 = continuous)
    vec4 wallRect;   // xy: item origin in backdrop px, zw: backdrop size px
    vec4 tint;       // rgb tint, a = strength
    vec4 look;       // x refraction px, y bezel width px, z rim strength, w sharp mix
    vec4 tone;       // x brightness, y saturation, z lift (+white/-black), w grain
    vec4 shadowP;    // x opacity, y blur sigma px, z y-offset px, w body alpha
    vec2 lightDir;   // direction light travels from (unit-ish), e.g. (-0.5,-0.85)
    float hover;     // 0..1 pointer emphasis
    float chroma;    // chromatic split 0..0.2
    vec4 hole;       // transparent window in body px (x, y, w, h); w <= 0: none (web islands)
    float holeRadius;
};
layout(binding = 1) uniform sampler2D blurTex;
layout(binding = 2) uniform sampler2D sharpTex;

float sdShape(vec2 p) {
    vec2 b = itemSize * 0.5 - vec2(pad);
    float r = clamp(radius, 0.0, min(b.x, b.y));
    vec2 q = abs(p) - b + vec2(r);
    vec2 m = max(q, vec2(0.0));
    float n = max(exponent, 1.5);
    float len = pow(pow(m.x, n) + pow(m.y, n), 1.0 / n);
    return min(max(q.x, q.y), 0.0) + len - r;
}

vec3 sampleBackdrop(vec2 px, vec2 offset) {
    vec2 inv = 1.0 / max(wallRect.zw, vec2(1.0));
    vec2 base = wallRect.xy + px;
    vec2 uvR = (base + offset * (1.0 + chroma)) * inv;
    vec2 uvG = (base + offset) * inv;
    vec2 uvB = (base + offset * (1.0 - chroma)) * inv;
    vec3 s = vec3(texture(sharpTex, uvR).r, texture(sharpTex, uvG).g, texture(sharpTex, uvB).b);
    vec3 b = vec3(texture(blurTex, uvR).r, texture(blurTex, uvG).g, texture(blurTex, uvB).b);
    return mix(b, s, clamp(look.w, 0.0, 1.0));
}

void main() {
    vec2 px = qt_TexCoord0 * itemSize;
    vec2 p = px - itemSize * 0.5;
    float d = sdShape(p);
    float inside = clamp(0.5 - d, 0.0, 1.0);

    // Shadow: gaussian fall-off of the offset shape, only outside the body.
    float ds = sdShape(p - vec2(0.0, shadowP.z));
    float sigma = max(shadowP.y, 0.5);
    float sd = max(ds, 0.0);
    float shadow = shadowP.x * exp(-(sd * sd) / (2.0 * sigma * sigma)) * (1.0 - inside);

    vec4 body = vec4(0.0);
    vec3 light = vec3(0.0);
    if (inside > 0.0) {
        float e = 0.75;
        vec2 grad = vec2(sdShape(p + vec2(e, 0.0)) - sdShape(p - vec2(e, 0.0)),
                         sdShape(p + vec2(0.0, e)) - sdShape(p - vec2(0.0, e)));
        float gl = length(grad);
        vec2 nrm = gl > 1e-4 ? grad / gl : vec2(0.0);
        float depth = max(-d, 0.0);
        float bezel = max(look.y, 1.0);
        float t = clamp(1.0 - depth / bezel, 0.0, 1.0);
        // Convex rim: pixels near the edge look at backdrop further inside.
        float bend = look.x * t * t * (1.0 + 0.35 * t);
        vec3 c = sampleBackdrop(px, -nrm * bend);

        float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
        c = mix(vec3(l), c, tone.y);
        c *= tone.x;
        c = tone.z >= 0.0 ? mix(c, vec3(1.0), tone.z) : mix(c, vec3(0.0), -tone.z);
        c = mix(c, tint.rgb, clamp(tint.a, 0.0, 1.0));
        float grain = fract(sin(dot(floor(px), vec2(12.9898, 78.233))) * 43758.5453) - 0.5;
        c += grain * tone.w;

        float a = inside * clamp(shadowP.w, 0.0, 1.0);
        if (hole.z > 0.0) {
            // Web islands: the page is composed *below* this layer, keep it visible.
            vec2 hb = hole.zw * 0.5;
            vec2 hp = (px - vec2(pad)) - (hole.xy + hb);
            float hr = clamp(holeRadius, 0.0, min(hb.x, hb.y));
            vec2 hq = abs(hp) - hb + vec2(hr);
            float dh = min(max(hq.x, hq.y), 0.0) + length(max(hq, vec2(0.0))) - hr;
            a *= clamp(0.5 + dh, 0.0, 1.0);
        }
        body = vec4(clamp(c, 0.0, 1.0) * a, a);

        vec2 L = normalize(lightDir + vec2(1e-5));
        float facing = dot(nrm, L);
        float spec = pow(max(facing, 0.0), 2.0) + 0.45 * pow(max(-facing, 0.0), 2.0);
        float rimLine = 1.0 - smoothstep(0.0, 1.6, depth);
        float rimGlow = t * t;
        float rim = look.z * (rimLine * (0.28 + 0.72 * spec) + rimGlow * 0.22 * spec);
        light = vec3(rim + hover * 0.035) * inside;
    }
    vec4 outc = body + vec4(0.0, 0.0, 0.0, shadow) * (1.0 - body.a);
    outc.rgb += light;
    outc.a = clamp(outc.a + dot(light, vec3(0.333)) * 0.5, 0.0, 1.0);
    fragColor = outc * qt_Opacity;
}
