"""Script de teste de integração end-to-end."""
import json
import urllib.request
import sys


def api(method, path, body=None):
    url = "http://localhost:8000" + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": e.read().decode()}


def main():
    print("=" * 60)
    print("TESTE DE INTEGRAÇÃO — FGI Sistema")
    print("=" * 60)

    # --- 1. Status da API ---
    print("\n[1] Status da API")
    r = api("GET", "/")
    print(f"    {r}")

    # --- 2. Colaboradores cadastrados ---
    print("\n[2] Colaboradores ativos")
    ativos = api("GET", "/employees?status=ativo")
    print(f"    Total: {len(ativos)}")

    # --- 3. Limpar pendentes duplicados ---
    print("\n[3] Verificar atestados pendentes")
    pendentes = api("GET", "/atestados?status=pendente_validacao")
    print(f"    Pendentes encontrados: {len(pendentes)}")

    vistos = {}
    rejeitar = []
    confirmar_ids = []
    for a in sorted(pendentes, key=lambda x: x["id"]):
        cid = a["colaborador_id"]
        if cid in vistos:
            rejeitar.append(a["id"])
        else:
            vistos[cid] = a["id"]
            confirmar_ids.append(a["id"])

    print(f"    Para confirmar: {len(confirmar_ids)}, para rejeitar (duplicatas): {len(rejeitar)}")

    for id in rejeitar:
        api("PATCH", f"/atestados/{id}/rejeitar")

    # --- 4. Confirmar atestados ---
    print("\n[4] Confirmando atestados")
    ok = 0
    alertas_dup = 0
    for id in confirmar_ids:
        r = api("PATCH", f"/atestados/{id}/confirmar",
                {"usuario": "teste_integracao", "forcar_duplicidade": False})
        if r.get("confirmado"):
            ok += 1
        elif r.get("alerta_duplicidade"):
            alertas_dup += 1
            # Força confirmação mesmo com alerta
            r2 = api("PATCH", f"/atestados/{id}/confirmar",
                     {"usuario": "teste_integracao", "forcar_duplicidade": True})
            if r2.get("confirmado"):
                ok += 1

    confirmados = api("GET", "/atestados?status=confirmado")
    print(f"    Confirmados: {ok} | Total no banco: {len(confirmados)}")

    # --- 5. Prévia do período ---
    print("\n[5] Prévia março/2026")
    previa = api("GET", "/reports/2026/3/preview")
    print(f"    Pode gerar: {previa.get('pode_gerar')}")
    print(f"    Pendências: {previa.get('pendencias')}")
    print(f"    Colaboradores: {previa.get('totais', {}).get('num_colaboradores') if previa.get('totais') else 'N/A'}")
    if previa.get("totais"):
        t = previa["totais"]
        print(f"    Total FGI:         R$ {t['total_fgi']:>10,.2f}   (esperado: R$ 7.173,76)")
        print(f"    Total c/ encargos: R$ {t['total_com_encargos']:>10,.2f}   (esperado: R$ 11.635,84)")
        print(f"    Total final:       R$ {t['total_final']:>10,.2f}   (esperado: R$ 12.161,78)")

    if previa.get("alertas"):
        print(f"    Alertas internos ({len(previa['alertas'])}):")
        for a in previa["alertas"]:
            print(f"      [{a['tipo']}] {a['colaborador_nome']}: {a['mensagem']}")

    # --- 6. Gerar Excel ---
    if previa.get("pode_gerar"):
        print("\n[6] Gerando Excel")
        r = api("POST", "/reports/2026/3/generate")
        print(f"    {r.get('mensagem')}")
        print(f"    Colaboradores: {r.get('num_colaboradores')}")
        print(f"    Total final: R$ {r.get('total_final', 0):,.2f}")
        print(f"    Download: GET http://localhost:8000/reports/2026/3/download")
    else:
        print("\n[6] Excel NÃO gerado — pendências bloqueando:")
        for p in previa.get("pendencias", []):
            print(f"    {p}")

    # --- 7. Status final do período ---
    print("\n[7] Status do período")
    status = api("GET", "/reports/2026/3/status")
    print(f"    {status}")

    print("\n" + "=" * 60)
    print("TESTE CONCLUÍDO")
    print("=" * 60)


if __name__ == "__main__":
    main()
