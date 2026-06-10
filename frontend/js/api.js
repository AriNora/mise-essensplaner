/**
 * Duenner API-Client. Buendelt alle HTTP-Aufrufe an /api/... an einer Stelle,
 * damit die Views (app.js) sich nicht um fetch-Details kuemmern muessen.
 */
async function request(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // Rezepte
  listRecipes: (search = "", limit = 50, offset = 0) =>
    request(`/api/recipes?search=${encodeURIComponent(search)}&limit=${limit}&offset=${offset}`),
  getRecipe: (id) => request(`/api/recipes/${id}`),
  createRecipe: (data) => request(`/api/recipes`, { method: "POST", body: JSON.stringify(data) }),
  updateRecipe: (id, data) => request(`/api/recipes/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  deleteRecipe: (id) => request(`/api/recipes/${id}`, { method: "DELETE" }),
  // Bild-Upload braucht FormData (kein JSON) -> eigener fetch ohne JSON-Header.
  uploadRecipeImage: async (id, file) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`/api/recipes/${id}/image`, { method: "POST", body: fd });
    if (!res.ok) {
      let detail = "Upload fehlgeschlagen";
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  },
  deleteRecipeImage: (id) => request(`/api/recipes/${id}/image`, { method: "DELETE" }),

  // Import (liefert einen Entwurf, der im Editor geprüft wird – speichert nichts)
  importFromUrl: (url) => request(`/api/import/url`, { method: "POST", body: JSON.stringify({ url }) }),
  importFromText: (text, name) => request(`/api/import/text`, { method: "POST", body: JSON.stringify({ text, name }) }),

  // Zutaten (Autocomplete)
  listIngredients: (search = "") => request(`/api/ingredients?search=${encodeURIComponent(search)}`),

  // Plan
  getPlan: () => request(`/api/plan`),
  addToPlan: (data) => request(`/api/plan`, { method: "POST", body: JSON.stringify(data) }),
  updatePlanEntry: (id, data) => request(`/api/plan/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  removePlanEntry: (id) => request(`/api/plan/${id}`, { method: "DELETE" }),
  clearPlan: () => request(`/api/plan`, { method: "DELETE" }),
  shoppingList: () => request(`/api/plan/shopping-list`),
  prepPlan: () => request(`/api/plan/prep-plan`),
};
