"""Genera imagenes SINTETICAS de un dron generico con etiquetas YOLO (Blender 4.x, solo bpy).

Escena abstracta: plano de terreno, bloques tipo edificio, cielo (color de fondo) y un dron
generico hecho con primitivas. No representa ninguna instalacion real, civil o militar.

Uso:
  blender --background --python blender/generate_scene.py -- --out <carpeta> --n 4 --seed 42

Salida por toma i:  drone_{i:03d}.png  y  drone_{i:03d}.txt  (``0 cx cy w h`` normalizados,
origen arriba-izquierda, formato YOLO) mas ``manifest.json``. La caja se calcula proyectando
las 8 esquinas de la caja envolvente de cada pieza del dron con ``world_to_camera_view``.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Euler, Vector

RES_X, RES_Y = 640, 480
CLASS_ID = 0  # 0 = drone


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--n", type=int, default=4)
    p.add_argument("--seed", type=int, default=42)
    # CYCLES por CPU es el valor por defecto porque no depende de la GPU ni de su controlador.
    # BLENDER_WORKBENCH es más rápido, pero en algunos equipos sus shaders no compilan en modo
    # --background y Blender se cierra (observado el 2026-11-11 con Blender 4.4.3 en Windows).
    p.add_argument("--engine", choices=("CYCLES", "BLENDER_WORKBENCH"), default="CYCLES")
    p.add_argument("--samples", type=int, default=32, help="muestras de Cycles")
    return p.parse_args(argv)


def make_material(name: str, rgb: tuple[float, float, float]) -> "bpy.types.Material":
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (rgb[0], rgb[1], rgb[2], 1.0)
    return mat


def add_box(name, loc, scale, mat):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = scale
    obj.data.materials.append(mat)
    return obj


def add_cyl(name, loc, radius, depth, mat):
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, location=loc, vertices=24)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.materials.append(mat)
    return obj


def build_world(rng: random.Random) -> None:
    mat_ground = make_material("terreno", (0.35, 0.42, 0.30))
    bpy.ops.mesh.primitive_plane_add(size=600.0, location=(0, 0, 0))
    ground = bpy.context.active_object
    ground.name = "terreno"
    ground.data.materials.append(mat_ground)
    greys = [(0.62, 0.60, 0.58), (0.72, 0.70, 0.66), (0.55, 0.57, 0.62), (0.78, 0.74, 0.68)]
    for i in range(18):
        ang = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(45.0, 130.0)
        w, d, h = rng.uniform(8, 22), rng.uniform(8, 22), rng.uniform(8, 45)
        add_box(f"bloque_{i:02d}", (r * math.cos(ang), r * math.sin(ang), h / 2),
                (w, d, h), make_material(f"muro_{i}", rng.choice(greys)))
    world = bpy.data.worlds.new("cielo")
    world.color = (0.55, 0.74, 0.95)
    world.use_nodes = False
    bpy.context.scene.world = world
    # Luz direccional genérica (necesaria en Cycles; Workbench la ignora).
    sun_data = bpy.data.lights.new("sol", "SUN")
    sun_data.energy = 3.0
    sun = bpy.data.objects.new("sol", sun_data)
    sun.rotation_euler = Euler((math.radians(50.0), 0.0, math.radians(30.0)))
    bpy.context.collection.objects.link(sun)


def build_drone(rng: random.Random):
    """Dron generico (cuerpo, brazos en X y 4 rotores). Devuelve (empty_raiz, [mallas])."""
    mat_body = make_material("dron_cuerpo", (0.95, 0.35, 0.05))
    mat_arm = make_material("dron_brazo", (0.08, 0.08, 0.10))
    mat_rotor = make_material("dron_rotor", (0.20, 0.20, 0.24))
    parts = [add_box("dron_cuerpo", (0, 0, 0), (0.30, 0.30, 0.09), mat_body)]
    for k, ang in enumerate((45.0, -45.0)):
        arm = add_box(f"dron_brazo_{k}", (0, 0, 0), (1.25, 0.05, 0.03), mat_arm)
        arm.rotation_euler = Euler((0, 0, math.radians(ang)))
        parts.append(arm)
    for k, (sx, sy) in enumerate(((1, 1), (1, -1), (-1, 1), (-1, -1))):
        parts.append(add_cyl(f"dron_rotor_{k}", (sx * 0.44, sy * 0.44, 0.06), 0.20, 0.015, mat_rotor))
    root = bpy.data.objects.new("dron_generico", None)
    bpy.context.collection.objects.link(root)
    for obj in parts:
        obj.parent = root
    root.location = (rng.uniform(-4, 4), rng.uniform(-4, 4), rng.uniform(10, 25))
    root.rotation_euler = Euler((math.radians(rng.uniform(-8, 8)), math.radians(rng.uniform(-8, 8)),
                                 math.radians(rng.uniform(0, 360))))
    return root, parts


def drone_bbox_ndc(scene, cam, parts):
    """Caja envolvente normalizada (x0, y0, x1, y1), origen abajo-izquierda, y si todas las esquinas
    estan delante de la camara."""
    xs, ys, in_front = [], [], True
    for obj in parts:
        mw = obj.matrix_world
        # Vértices reales de la malla (no las esquinas de la caja envolvente): la etiqueta queda
        # ajustada a lo que se ve, también en piezas rotadas y en los rotores cilíndricos.
        for v in obj.data.vertices:
            co = world_to_camera_view(scene, cam, mw @ v.co)
            xs.append(co.x)
            ys.append(co.y)
            in_front = in_front and co.z > 0.0
    return min(xs), min(ys), max(xs), max(ys), in_front


def place_camera(scene, cam, root, parts, rng: random.Random, depsgraph_fn):
    """Coloca la camara a 10-22 m del dron mirando hacia el con un pequeno desvio; reintenta si el dron
    queda fuera de cuadro o tapado por un bloque."""
    target = root.matrix_world.translation
    for _ in range(60):
        dist = rng.uniform(10.0, 22.0)
        az = rng.uniform(0, 2 * math.pi)
        height = rng.uniform(2.0, 18.0)
        horiz = math.sqrt(max(dist * dist - (height - target.z) ** 2, 1.0))
        cam.location = (target.x + horiz * math.cos(az), target.y + horiz * math.sin(az), height)
        aim = target + Vector((rng.uniform(-1.5, 1.5), rng.uniform(-1.5, 1.5), rng.uniform(-1.0, 1.0)))
        direction = aim - Vector(cam.location)
        cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        depsgraph_fn()
        x0, y0, x1, y1, ok = drone_bbox_ndc(scene, cam, parts)
        if not ok or x0 < 0.02 or y0 < 0.02 or x1 > 0.98 or y1 > 0.98:
            continue
        # oclusion: el rayo camara -> dron debe llegar a una pieza del dron
        d = target - Vector(cam.location)
        hit, _loc, _n, _i, hit_obj, _m = scene.ray_cast(bpy.context.view_layer.depsgraph,
                                                        Vector(cam.location), d.normalized(), distance=d.length + 1.0)
        if hit and hit_obj is not None and not hit_obj.name.startswith("dron_"):
            continue
        return (x0, y0, x1, y1)
    raise RuntimeError("no se encontro una toma valida del dron tras 60 intentos")


def main() -> None:
    args = parse_args()
    # Ruta absoluta: Blender no resuelve las rutas relativas de render contra el directorio actual.
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = args.engine
    scene.render.resolution_x, scene.render.resolution_y = RES_X, RES_Y
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    if args.engine == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.samples = args.samples
        scene.cycles.use_denoising = False
        scene.cycles.seed = args.seed
    else:
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
        scene.display.shading.show_shadows = True
    scene.view_settings.view_transform = "Standard"

    build_world(rng)
    root, parts = build_drone(rng)
    cam_data = bpy.data.cameras.new("camara")
    cam_data.lens = 35.0
    cam = bpy.data.objects.new("camara", cam_data)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam

    def refresh():
        bpy.context.view_layer.update()

    manifest = {"descripcion": "Imagenes SINTETICAS (Blender, escena abstracta). Etiqueta YOLO: clase cx cy w h.",
                "clases": ["drone"], "resolucion": [RES_X, RES_Y], "semilla": args.seed,
                "motor": args.engine, "blender": bpy.app.version_string, "imagenes": []}
    for i in range(args.n):
        root.location = (rng.uniform(-4, 4), rng.uniform(-4, 4), rng.uniform(10, 25))
        root.rotation_euler = Euler((math.radians(rng.uniform(-8, 8)), math.radians(rng.uniform(-8, 8)),
                                     math.radians(rng.uniform(0, 360))))
        refresh()
        x0, y0, x1, y1 = place_camera(scene, cam, root, parts, rng, refresh)
        # YOLO: origen arriba-izquierda
        cx, cy = (x0 + x1) / 2.0, 1.0 - (y0 + y1) / 2.0
        w, h = x1 - x0, y1 - y0
        stem = f"drone_{i:03d}"
        scene.render.filepath = str(out / f"{stem}.png")
        bpy.ops.render.render(write_still=True)
        (out / f"{stem}.txt").write_text(f"{CLASS_ID} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n", encoding="utf-8")
        manifest["imagenes"].append({"imagen": f"{stem}.png", "etiqueta": f"{stem}.txt",
                                     "yolo": [CLASS_ID, round(cx, 6), round(cy, 6), round(w, 6), round(h, 6)]})
        print(f"[generate_scene] {stem}: caja YOLO = {CLASS_ID} {cx:.4f} {cy:.4f} {w:.4f} {h:.4f}")
    (out / "classes.txt").write_text("drone\n", encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[generate_scene] listo: {args.n} imagenes en {out}")


main()
