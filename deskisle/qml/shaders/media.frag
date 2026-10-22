// Island background media: rounded-rect mask with a feathered edge.
// Output is premultiplied alpha (the source texture already is).
#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 itemSize;   // px
    float radius;    // corner radius px
    float feather;   // fade width px (0 = crisp edge)
    float amount;    // media opacity 0..1
};
layout(binding = 1) uniform sampler2D source;

float roundBox(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + vec2(r);
    return min(max(q.x, q.y), 0.0) + length(max(q, vec2(0.0))) - r;
}

void main() {
    vec2 p = qt_TexCoord0 * itemSize - itemSize * 0.5;
    float r = min(radius, min(itemSize.x, itemSize.y) * 0.5);
    float d = roundBox(p, itemSize * 0.5, r);          // < 0 inside
    float edge = feather > 0.5 ? clamp(-d / feather, 0.0, 1.0) : clamp(0.5 - d, 0.0, 1.0);
    edge = edge * edge * (3.0 - 2.0 * edge);
    fragColor = texture(source, qt_TexCoord0) * (edge * amount * qt_Opacity);
}
