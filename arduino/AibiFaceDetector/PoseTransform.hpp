#pragma once
#include <cmath>
#include "Settings.hpp"

namespace pose {
struct Point { float x, y; };
struct Spec {
    int quarterTurns, tiltDegrees;
    bool mirrored;
    int width, height;
};
inline Spec specification(uint8_t index) {
    const int turn = (index / settings::rollAngleCount) % 4;
    return {turn, settings::rollAngles[index % settings::rollAngleCount],
            index >= 4*settings::rollAngleCount,
            (turn & 1) ? settings::height : settings::width,
            (turn & 1) ? settings::width : settings::height};
}
struct Transform {
    float xx, xy, x0, yx, yy, y0;
    Point map(float x, float y) const {
        return {xx*x + xy*y + x0, yx*x + yy*y + y0};
    }
};

// Inverse of model-space mirror, tilt and quarter-turn. The same mapping
// samples the camera pixels and maps all four detection box corners back.
inline Transform toCamera(uint8_t index) {
    const auto p = specification(index);
    const float radians = p.tiltDegrees * 0.017453292519943295f;
    const float c = std::cos(radians), s = std::sin(radians);
    const float cx = (p.width - 1) * 0.5f, cy = (p.height - 1) * 0.5f;
    const float m = p.mirrored ? -1 : 1;
    const float offset = p.mirrored ? p.width - 1 : 0;
    const Transform t{c*m, s, cx+c*(offset-cx)-s*cy,
                      -s*m, c, cy-s*(offset-cx)-c*cy};
    switch (p.quarterTurns) {
        case 1: return {t.yx, t.yy, t.y0, -t.xx, -t.xy, settings::height-1-t.x0};
        case 2: return {-t.xx, -t.xy, settings::width-1-t.x0, -t.yx, -t.yy, settings::height-1-t.y0};
        case 3: return {-t.yx, -t.yy, settings::width-1-t.y0, t.xx, t.xy, t.x0};
        default: return t;
    }
}

// No shared mutable state: the inference task exclusively owns this search.
// Prefer nearby tilts after losing a known orientation; otherwise try the
// cardinal orientations before the remaining tilt/reflection variants.
class Search {
    uint8_t preferred = 0;
    uint32_t tried = 0;
public:
    uint8_t next(uint8_t used, bool found) {
        if (found) { preferred = used; tried = 0; return used; }
        tried |= uint32_t(1) << used;
        const unsigned base = (preferred/settings::rollAngleCount)*settings::rollAngleCount;
        for (unsigned i = 0; i < settings::rollAngleCount; ++i) {
            const uint8_t candidate = base+i;
            if (!(tried & (uint32_t(1) << candidate))) return candidate;
        }
        for (const uint8_t candidate : settings::poseSearchOrder)
            if (!(tried & (uint32_t(1) << candidate))) return candidate;
        tried = 0;
        return preferred;
    }
};

// Properties checked on the actual MCU at startup, without model test boxes.
inline bool geometryValid() {
    constexpr float tolerance = 0.002f;
    const Point origins[2][4] = {
        {{0,0}, {0,settings::height-1}, {settings::width-1,settings::height-1}, {settings::width-1,0}},
        {{settings::width-1,0}, {0,0}, {0,settings::height-1}, {settings::width-1,settings::height-1}}
    };
    uint32_t orderMask = 0;
    for (const auto index : settings::poseSearchOrder) {
        if (index >= settings::poseCount || (orderMask & (uint32_t(1)<<index))) return false;
        orderMask |= uint32_t(1)<<index;
        const auto p = specification(index);
        if (p.width*p.height != settings::width*settings::height) return false;
        const auto t = toCamera(index);
        const auto center = t.map((p.width-1)*0.5f, (p.height-1)*0.5f);
        if (std::fabs(center.x-(settings::width-1)*0.5f) > tolerance ||
            std::fabs(center.y-(settings::height-1)*0.5f) > tolerance) return false;
        const auto a = t.map(10,20), b = t.map(13,24);
        if (std::fabs((a.x-b.x)*(a.x-b.x)+(a.y-b.y)*(a.y-b.y)-25) > tolerance) return false;
        if (std::fabs(t.xx*t.yy-t.xy*t.yx-(p.mirrored ? -1 : 1)) > tolerance) return false;
        if (p.tiltDegrees == 0) {
            const auto origin = t.map(0,0), opposite = t.map(p.width-1,p.height-1);
            const auto expected = origins[p.mirrored ? 1 : 0][p.quarterTurns];
            if (origin.x != expected.x || origin.y != expected.y ||
                opposite.x != settings::width-1-expected.x || opposite.y != settings::height-1-expected.y) return false;
        }
    }
    Search search;
    uint32_t visited = 0;
    uint8_t next = 0;
    for (unsigned i = 0; i < settings::poseCount; ++i) {
        if (visited & (uint32_t(1)<<next)) return false;
        visited |= uint32_t(1)<<next;
        next = search.next(next, false);
    }
    if (visited != orderMask || search.next(6,true) != 6 || search.next(6,true) != 6) return false;
    return true;
}
}
