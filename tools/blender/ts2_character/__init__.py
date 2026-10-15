"""TimeSplitters 2 character models (.xbr) in Blender.

File > Import > TimeSplitters 2 character (.xbr) converts the model with
tools/ts2gltf.py (vendored into the add-on by tools/blender/build_addon.py)
and loads the result with Blender's glTF importer. The armature remembers
the .xbr it came from. File > Export > TimeSplitters 2 character (.xbr)
writes the armature's meshes to a .glb with the settings ts2gltf expects
and imports that over the remembered .xbr (ts2gltf.py fromgltf), new
textures included. The TS2 tab of the 3D view's sidebar has the same, and
"Write into mod folder", which lays the files out for tools/ts2mod.py.

docs/formats/xbr.md, "Editing in Blender", says what survives the trip.
"""

import importlib
import os
import shutil
import sys
import tempfile
import types

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel
from bpy_extras.io_utils import ExportHelper, ImportHelper

bl_info = {      # read only when installed as a classic add-on (the manifest replaces it)
    "name": "TimeSplitters 2 character",
    "author": "split2-recomp",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "File > Import/Export, 3D View > Sidebar > TS2",
    "description": "Import and export TimeSplitters 2 (Xbox) character models (.xbr)",
    "category": "Import-Export",
}

SOURCE = "ts2_source"          # custom property on the armature: the .xbr it came from
TEXTURES = "ts2_textures"


# --------------------------------------------------------------------------
# The converter


def prefs(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def tools(context=None):
    """The ts2gltf module: the copy in vendor/, else the tools folder set in
    the add-on's preferences (a checkout's tools/)."""
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
    path = here
    if not os.path.exists(os.path.join(here, "ts2gltf.py")):
        p = prefs(context)
        path = bpy.path.abspath(p.tools_dir) if p and p.tools_dir else ""
        if not os.path.exists(os.path.join(path, "ts2gltf.py")):
            raise RuntimeError("ts2gltf.py not found: install the add-on zip built by tools/blender/build_addon.py, "
                               "or set the tools folder in the add-on's preferences")
    if path not in sys.path:
        sys.path.insert(0, path)
    import ts2gltf
    if os.path.dirname(os.path.abspath(ts2gltf.__file__)) != os.path.abspath(path):
        ts2gltf = importlib.reload(ts2gltf)
    return ts2gltf


def bindpose_paths(context=None):
    """The folder with human_19_bindpose.raw: the one in the preferences, or
    anim/data/ts2 under it (an unpacked fe_anim.pak)."""
    p = prefs(context)
    d = bpy.path.abspath(p.bindpose_dir) if p and p.bindpose_dir else ""
    if not d:
        return []
    for cand in (d, os.path.join(d, "anim", "data", "ts2")):
        if os.path.isdir(cand) and any("bindpose" in f.lower() and f.lower().endswith(".raw") for f in os.listdir(cand)):
            return [cand]
    if os.path.isfile(d):
        return [d]
    return []


def default_textures(context, arm=None):
    if arm is not None and arm.get(TEXTURES):
        return arm[TEXTURES]
    p = prefs(context)
    return bpy.path.abspath(p.textures_dir) if p and p.textures_dir else ""


def find_armature(context):
    ob = context.active_object
    while ob is not None and ob.type != "ARMATURE":
        ob = ob.parent
    if ob is None:
        for o in context.selected_objects:
            if o.type == "ARMATURE":
                return o
    return ob


def import_xbr(context, path, textures):
    G = tools(context)
    _, xbr = G.X.load(path)
    name = os.path.splitext(os.path.basename(path))[0]
    warnings = []
    bps = G.load_bindposes(bindpose_paths(context))
    glb = G.export_glb(xbr, name, textures or None, bps, warn=warnings.append)
    tmp = tempfile.mkdtemp(prefix="ts2_")
    try:
        gpath = os.path.join(tmp, name + ".glb")
        with open(gpath, "wb") as f:
            f.write(glb)
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=gpath)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    new = [o for o in bpy.data.objects if o not in before]
    arms = [o for o in new if o.type == "ARMATURE"]
    for a in arms:
        a[SOURCE] = os.path.abspath(path)
        a[TEXTURES] = textures or ""
    return arms, warnings


def export_xbr(context, out, base=None, textures=None, texture_dir=None, retexture=False, regenerate=False):
    """Writes the armature hierarchy (the active one, and every selected
    armature, for a model put together from two) over its base .xbr.
    Returns the report lines."""
    G = tools(context)
    active = find_armature(context)
    if active is None:
        raise RuntimeError("select the character's armature (or one of its meshes)")
    arms = [active] + [o for o in context.selected_objects if o.type == "ARMATURE" and o != active]
    base = base or active.get(SOURCE)
    if not base or not os.path.exists(base):
        raise RuntimeError("no base .xbr: import the model with File > Import > TimeSplitters 2 character, "
                           "or give the base file")
    textures = textures if textures is not None else default_textures(context, active)
    objs = set(arms)
    for a in arms:
        objs.update(o for o in a.children_recursive if o.type == "MESH")
    view = context.view_layer
    saved_sel = [o for o in view.objects if o.select_get()]
    saved_active = view.objects.active
    tmp = tempfile.mkdtemp(prefix="ts2_")
    try:
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        for o in view.objects:
            o.select_set(o in objs)
        view.objects.active = active
        gpath = os.path.join(tmp, "model.glb")
        bpy.ops.export_scene.gltf(filepath=gpath, export_format="GLB", use_selection=True, export_yup=True,
                                  export_apply=False, export_skins=True, export_animations=False,
                                  export_morph=False, export_texcoords=True, export_normals=True)
        args = types.SimpleNamespace(textures=textures or None, texture_dir=texture_dir or None, retexture=retexture)
        _, xbr = G.X.load(base)
        mt, tex_dir = G.materials_for(args, base, xbr, out)
        new, report, stats = G.import_glb(xbr, gpath, regenerate=regenerate,
                                          bindposes=G.load_bindposes(bindpose_paths(context)), materials=mt)
        data, written = G.write_model(new, out, tex_dir)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        for o in view.objects:
            o.select_set(o in saved_sel)
        view.objects.active = saved_active
    report = list(report) + ["wrote " + p for p in written]
    report.append("%s: %d bytes, %d materials; %d sections kept, %d rebuilt, %d removed; %d vertices snapped"
                  % (out, len(data), len(new["materials"]), stats["sections_kept"], stats["sections_rebuilt"],
                     stats["sections_removed"], stats["snapped"]))
    return report


def mod_path(base, mod_dir):
    """Where ts2mod's files/ wants the model: ob/chrincs for a front-end
    preview, ob/chrs otherwise."""
    sub = "chrincs" if "chrincs" in base.replace("\\", "/").split("/") else "chrs"
    return os.path.join(mod_dir, "files", "ob", sub, os.path.basename(base))


# --------------------------------------------------------------------------
# Operators


class TS2_OT_import(Operator, ImportHelper):
    """Import a TimeSplitters 2 character model"""
    bl_idname = "import_scene.ts2_xbr"
    bl_label = "Import TimeSplitters 2 character"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".xbr"
    filter_glob: StringProperty(default="*.xbr", options={"HIDDEN"})
    textures: StringProperty(name="Textures", subtype="DIR_PATH",
                             description="An unpacked pak folder holding textures/NNNN.xbt (chr.pak, or the level pak "
                                         "the model came from). Front-end previews carry their own")

    def invoke(self, context, event):
        if not self.textures:
            self.textures = default_textures(context)
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        try:
            arms, warnings = import_xbr(context, self.filepath, bpy.path.abspath(self.textures))
        except Exception as e:  # noqa: BLE001 - shown to the user
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        for w in warnings:
            self.report({"WARNING"}, w)
        if not bindpose_paths(context):
            self.report({"WARNING"}, "no bind pose folder in the add-on's preferences: joints placed at their vertices")
        self.report({"INFO"}, "imported %s (%d armature)" % (os.path.basename(self.filepath), len(arms)))
        return {"FINISHED"}


class ExportProps:
    base: StringProperty(name="Base .xbr", subtype="FILE_PATH",
                         description="The model the export is written over (pieces, bones, everything but geometry "
                                     "and materials). Default: the one the armature was imported from")
    textures: StringProperty(name="Textures", subtype="DIR_PATH",
                             description="Unpacked chr.pak: textures to embed in a front-end preview, and pictures "
                                         "to compare for Retexture")
    texture_dir: StringProperty(name="New textures", subtype="DIR_PATH",
                                description="Where new NNNN.xbt files go. Empty: <mod>/files/textures when the .xbr "
                                            "goes under a files/ folder, else textures/ beside it")
    retexture: BoolProperty(name="Retexture", default=False,
                            description="A material named after a texture id (m0_t0775) whose image was changed gets "
                                        "a new texture (needs Textures)")
    regenerate: BoolProperty(name="Regenerate", default=False,
                             description="Rebuild every section, also those whose triangles are unchanged")


class TS2_OT_export(Operator, ExportHelper, ExportProps):
    """Export the selected TimeSplitters 2 character over its .xbr"""
    bl_idname = "export_scene.ts2_xbr"
    bl_label = "Export TimeSplitters 2 character"
    filename_ext = ".xbr"
    filter_glob: StringProperty(default="*.xbr", options={"HIDDEN"})

    def invoke(self, context, event):
        arm = find_armature(context)
        if arm is not None:
            if not self.base:
                self.base = arm.get(SOURCE, "")
            if not self.textures:
                self.textures = default_textures(context, arm)
            if self.base:
                self.filepath = os.path.basename(self.base)
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        try:
            lines = export_xbr(context, self.filepath, bpy.path.abspath(self.base) if self.base else None,
                               bpy.path.abspath(self.textures) if self.textures else None,
                               bpy.path.abspath(self.texture_dir) if self.texture_dir else None,
                               self.retexture, self.regenerate)
        except Exception as e:  # noqa: BLE001 - shown to the user
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        for line in lines:
            print("ts2: " + line)
        self.report({"INFO"}, lines[-1])
        return {"FINISHED"}


class TS2_OT_write_mod(Operator, ExportProps):
    """Write the character into the mod folder: files/ob/chrs/<name>.xbr (ob/chrincs for a front-end preview)
and files/textures/NNNN.xbt, as tools/ts2mod.py build takes them"""
    bl_idname = "ts2.write_mod"
    bl_label = "Write into mod folder"
    mod_dir: StringProperty(name="Mod folder", subtype="DIR_PATH")

    def execute(self, context):
        arm = find_armature(context)
        mod_dir = self.mod_dir or context.scene.ts2_mod_dir or (prefs(context).mod_dir if prefs(context) else "")
        mod_dir = bpy.path.abspath(mod_dir)
        base = bpy.path.abspath(self.base) if self.base else (arm.get(SOURCE) if arm else None)
        if not mod_dir or not base:
            self.report({"ERROR"}, "set the mod folder, and select an imported character's armature")
            return {"CANCELLED"}
        out = mod_path(base, mod_dir)
        try:
            lines = export_xbr(context, out, base, bpy.path.abspath(self.textures) if self.textures else None,
                               None, self.retexture, self.regenerate)
        except Exception as e:  # noqa: BLE001 - shown to the user
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        for line in lines:
            print("ts2: " + line)
        self.report({"INFO"}, lines[-1])
        return {"FINISHED"}


class TS2_PT_panel(Panel):
    bl_label = "TimeSplitters 2"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TS2"

    def draw(self, context):
        col = self.layout.column()
        arm = find_armature(context)
        col.operator(TS2_OT_import.bl_idname, text="Import .xbr", icon="IMPORT")
        if arm is None:
            col.label(text="Select a character's armature")
            return
        col.label(text="Armature: " + arm.name)
        col.label(text="Base: " + os.path.basename(arm.get(SOURCE, "(none)")))
        col.operator(TS2_OT_export.bl_idname, text="Export .xbr", icon="EXPORT")
        col.separator()
        col.prop(context.scene, "ts2_mod_dir", text="Mod")
        col.operator(TS2_OT_write_mod.bl_idname, icon="FILE_FOLDER")


class TS2_Preferences(AddonPreferences):
    bl_idname = __package__
    bindpose_dir: StringProperty(name="Bind pose folder", subtype="DIR_PATH",
                                 description="The folder holding human_19_bindpose.raw, or an unpacked fe_anim.pak")
    textures_dir: StringProperty(name="Textures", subtype="DIR_PATH",
                                 description="Default textures source: an unpacked chr.pak")
    mod_dir: StringProperty(name="Mod folder", subtype="DIR_PATH", description="Default for Write into mod folder")
    tools_dir: StringProperty(name="Tools folder", subtype="DIR_PATH",
                              description="Only when the add-on has no vendored copy: split2-recomp's tools/")

    def draw(self, context):
        for prop in ("bindpose_dir", "textures_dir", "mod_dir", "tools_dir"):
            self.layout.prop(self, prop)


def menu_import(self, context):
    self.layout.operator(TS2_OT_import.bl_idname, text="TimeSplitters 2 character (.xbr)")


def menu_export(self, context):
    self.layout.operator(TS2_OT_export.bl_idname, text="TimeSplitters 2 character (.xbr)")


CLASSES = (TS2_Preferences, TS2_OT_import, TS2_OT_export, TS2_OT_write_mod, TS2_PT_panel)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.ts2_mod_dir = StringProperty(name="Mod folder", subtype="DIR_PATH",
                                                 description="Folder for Write into mod folder (ts2mod's source)")
    bpy.types.TOPBAR_MT_file_import.append(menu_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_export)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_export)
    del bpy.types.Scene.ts2_mod_dir
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
