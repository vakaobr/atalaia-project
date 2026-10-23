-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- The scenario compiler's entry points (core/include/atalaia/scenario.h): a
-- manifest's data tree in, an answer's JSON out.
--
--   check    {"ok": b, "problems": [{path, code, message, level}, ...]}
--   compile  the same, and without errors "id", "version" and "files":
--            {"mode.yaml": text, "field.lua": text}
--   literal  {"ok": true, "lua": the value as a Lua literal}, or
--            {"ok": false, "error": why Lua cannot hold it}
-- A tree that is not one gives {"error": why}; a tree nested past
-- tree.MAX_DEPTH levels is a problem, bad_manifest (PE24-113).
local main = {}

-- Each call loads only the modules its operation needs (the sources are parsed
-- again in every call's own state).
local tree = need("tree")

local obj = tree.object

local function problem_list(problems)
  local out = { n = #problems }
  for i, p in ipairs(problems) do
    out[i] = obj("path", p.path, "code", p.code, "message", p.message, "level", p.level)
  end
  return out
end

local function read(text)
  local ok, value = pcall(tree.read, text)
  if ok then
    return true, value
  end
  if type(value) == "table" and value.deep then
    return false,
      tree.json(obj(
        "ok",
        false,
        "problems",
        problem_list({
          {
            path = "",
            code = "bad_manifest",
            message = string.format(
              "the manifest is nested more than %d levels deep",
              tree.MAX_DEPTH
            ),
            level = "error",
          },
        })
      ))
  end
  if type(value) == "table" and value.tree then
    return false, tree.json(obj("error", value.tree))
  end
  error(value, 0) -- out of memory or time: core/src/scenario.c says so
end

function main.run(op, text, runtime)
  local ok, manifest = read(text)
  if not ok then
    return manifest
  end
  if op == "literal" then
    local done, lua = pcall(need("luagen").value, manifest)
    if done then
      return tree.json(obj("ok", true, "lua", lua))
    end
    if type(lua) == "table" and lua.lua then
      return tree.json(obj("ok", false, "error", lua.lua))
    end
    error(lua, 0)
  end
  local validator = need("validator")
  local problems = validator.validate(manifest)
  local bad = #validator.errors(problems) > 0
  local out = obj("ok", not bad, "problems", problem_list(problems))
  if op == "compile" and not bad then
    local done, pkg = pcall(need("package").build, manifest, runtime)
    if not done then
      if type(pkg) == "table" and pkg.lua then
        return tree.json(obj("error", "the compiled field.lua cannot be written: " .. pkg.lua))
      end
      error(pkg, 0)
    end
    out = obj(
      "ok",
      true,
      "problems",
      problem_list(problems),
      "id",
      pkg.id,
      "version",
      pkg.version,
      "files",
      obj("mode.yaml", pkg.mode_yaml, "field.lua", pkg.field_lua)
    )
  end
  return tree.json(out)
end

return main
