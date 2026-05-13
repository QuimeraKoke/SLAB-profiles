"use client";

import React, { useEffect, useState } from "react";
import AttachmentList from "@/components/ui/AttachmentList/AttachmentList";
import { api, ApiError } from "@/lib/api";
import { usePermission } from "@/lib/permissions";
import type { Contract, ContractCreateIn, ContractType } from "@/lib/types";
import styles from "./ContractsPanel.module.css";

interface Props {
  playerId: string;
}

const TYPE_LABEL: Record<ContractType, string> = {
  permanent: "Permanente",
  loan_in: "Préstamo (entra)",
  loan_out: "Préstamo (cedido)",
  youth: "Cantera",
};

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function classify(contract: Contract): "current" | "expired" | "future" {
  const today = todayISO();
  if (contract.start_date > today) return "future";
  if (contract.end_date < today) return "expired";
  return "current";
}

function formatMoney(amount: number | null, currency: string): string {
  if (amount === null) return "—";
  return `${currency} ${amount.toLocaleString("es-CL", { maximumFractionDigits: 0 })}`;
}

function formatDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("es-CL", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export default function ContractsPanel({ playerId }: Props) {
  const [contracts, setContracts] = useState<Contract[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Contract | "new" | null>(null);
  const [expandedAttachmentsId, setExpandedAttachmentsId] = useState<string | null>(null);
  // Action gates: the section is only mounted when view_contract is
  // granted (see ProfileHeader), but add/change/delete are independent
  // perms — assigned granularly per-user from the admin.
  const canAdd = usePermission("core.add_contract");
  const canChange = usePermission("core.change_contract");
  const canDelete = usePermission("core.delete_contract");

  const refresh = async () => {
    try {
      const data = await api<Contract[]>(`/players/${playerId}/contracts`);
      setContracts(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error al cargar contratos");
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playerId]);

  const handleSaved = () => {
    setEditing(null);
    refresh();
  };

  const handleDelete = async (contract: Contract) => {
    if (!confirm(`¿Borrar el contrato ${contract.start_date} → ${contract.season_label}?`)) return;
    try {
      await api(`/contracts/${contract.id}`, { method: "DELETE" });
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error al borrar");
    }
  };

  if (contracts === null) {
    return <div className={styles.panel}>Cargando contratos…</div>;
  }

  const redacted = contracts.length > 0 && !contracts[0].salary_visible;

  return (
    <div className={styles.panel}>
      <div className={styles.toolbar}>
        <h4 className={styles.title}>Contratos · {contracts.length}</h4>
        {!editing && canAdd && (
          <button type="button" className={styles.newBtn} onClick={() => setEditing("new")}>
            + Nuevo contrato
          </button>
        )}
      </div>

      {error && <div className={styles.error}>{error}</div>}
      {redacted && (
        <div className={styles.redactedHint}>
          Los montos están ocultos. Solo administradores pueden ver salarios y bonos.
        </div>
      )}

      {editing && (
        <ContractForm
          playerId={playerId}
          contract={editing === "new" ? null : editing}
          onSaved={handleSaved}
          onCancel={() => setEditing(null)}
        />
      )}

      {contracts.length === 0 && !editing ? (
        <div className={styles.empty}>Aún no hay contratos para este jugador.</div>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Estado</th>
                <th>Tipo</th>
                <th>Inicio → Fin</th>
                <th>%</th>
                <th>Total bruto</th>
                <th>Bonos / Opciones</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {contracts.map((c) => {
                const status = classify(c);
                const attachmentsOpen = expandedAttachmentsId === c.id;
                return (
                  <React.Fragment key={c.id}>
                    <tr className={status === "current" ? styles.current : ""}>
                      <td>
                        <span className={`${styles.tag} ${styles[status]}`}>
                          {status === "current" ? "Vigente" : status === "future" ? "Futuro" : "Vencido"}
                        </span>
                      </td>
                      <td>{TYPE_LABEL[c.contract_type]}</td>
                      <td>
                        <div>{formatDate(c.start_date)}</div>
                        <div style={{ color: "#6b7280" }}>
                          → {c.season_label} ({formatDate(c.end_date)})
                        </div>
                      </td>
                      <td>{(c.ownership_percentage * 100).toFixed(0)}%</td>
                      <td className={styles.amount}>
                        {c.salary_visible ? formatMoney(c.total_gross_amount, c.salary_currency) : "—"}
                      </td>
                      <td>
                        {c.salary_visible ? (
                          <BonusList contract={c} />
                        ) : (
                          <span style={{ color: "#9ca3af" }}>—</span>
                        )}
                      </td>
                      <td className={styles.actions}>
                        <button
                          type="button"
                          className={styles.iconBtn}
                          onClick={() => setExpandedAttachmentsId(attachmentsOpen ? null : c.id)}
                        >
                          {attachmentsOpen ? "Ocultar archivos" : "Archivos"}
                        </button>
                        {canChange && (
                          <button
                            type="button"
                            className={styles.iconBtn}
                            onClick={() => setEditing(c)}
                          >
                            Editar
                          </button>
                        )}
                        {canDelete && (
                          <button
                            type="button"
                            className={`${styles.iconBtn} ${styles.danger}`}
                            onClick={() => handleDelete(c)}
                          >
                            Borrar
                          </button>
                        )}
                      </td>
                    </tr>
                    {attachmentsOpen && (
                      <tr>
                        <td colSpan={7} style={{ background: "#f9fafb", padding: 12 }}>
                          <AttachmentList
                            sourceType="contract"
                            sourceId={c.id}
                            readOnly={!c.salary_visible}
                            hint="Adjuntos del contrato"
                          />
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function BonusList({ contract: c }: { contract: Contract }) {
  const items: { label: string; value: string }[] = [
    { label: "Bono fijo", value: c.fixed_bonus },
    { label: "Bono variable", value: c.variable_bonus },
    { label: "Aumento", value: c.salary_increase },
    { label: "Op. compra", value: c.purchase_option },
    { label: "Cláusula salida", value: c.release_clause },
    { label: "Op. renovación", value: c.renewal_option },
  ].filter((row) => row.value && row.value.toUpperCase() !== "NO");

  if (items.length === 0) return <span style={{ color: "#9ca3af" }}>—</span>;

  return (
    <div className={styles.note}>
      {items.map((row) => (
        <div key={row.label}>
          <strong>{row.label}:</strong> {row.value}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Form
// ---------------------------------------------------------------------------

interface FormProps {
  playerId: string;
  contract: Contract | null;
  onSaved: () => void;
  onCancel: () => void;
}

function ContractForm({ playerId, contract, onSaved, onCancel }: FormProps) {
  const isEdit = contract !== null;
  const [contractType, setContractType] = useState<ContractType>(
    contract?.contract_type ?? "permanent",
  );
  const [startDate, setStartDate] = useState(contract?.start_date ?? todayISO());
  const [endDate, setEndDate] = useState(contract?.end_date ?? todayISO());
  const [signingDate, setSigningDate] = useState(contract?.signing_date ?? "");
  const [ownership, setOwnership] = useState(
    String(contract?.ownership_percentage ?? 1),
  );
  const [totalGross, setTotalGross] = useState(
    contract?.total_gross_amount !== null && contract?.total_gross_amount !== undefined
      ? String(contract.total_gross_amount)
      : "",
  );
  const [currency, setCurrency] = useState(contract?.salary_currency ?? "CLP");
  const [fixedBonus, setFixedBonus] = useState(contract?.fixed_bonus ?? "");
  const [variableBonus, setVariableBonus] = useState(contract?.variable_bonus ?? "");
  const [salaryIncrease, setSalaryIncrease] = useState(contract?.salary_increase ?? "");
  const [purchaseOption, setPurchaseOption] = useState(contract?.purchase_option ?? "");
  const [releaseClause, setReleaseClause] = useState(contract?.release_clause ?? "");
  const [renewalOption, setRenewalOption] = useState(contract?.renewal_option ?? "");
  const [agentName, setAgentName] = useState(contract?.agent_name ?? "");
  const [notes, setNotes] = useState(contract?.notes ?? "");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (endDate < startDate) {
      setError("La fecha de fin debe ser igual o posterior al inicio.");
      return;
    }
    const ownershipNum = Number(ownership);
    if (Number.isNaN(ownershipNum) || ownershipNum <= 0 || ownershipNum > 1) {
      setError("Porcentaje contrato debe estar entre 0 y 1 (ej. 0.75 para 75%).");
      return;
    }
    const grossNum = totalGross ? Number(totalGross) : null;
    if (totalGross && Number.isNaN(grossNum)) {
      setError("Total bruto inválido.");
      return;
    }

    const payload: ContractCreateIn = {
      player_id: playerId,
      contract_type: contractType,
      start_date: startDate,
      end_date: endDate,
      signing_date: signingDate || null,
      ownership_percentage: ownershipNum,
      total_gross_amount: grossNum,
      salary_currency: currency,
      fixed_bonus: fixedBonus,
      variable_bonus: variableBonus,
      salary_increase: salaryIncrease,
      purchase_option: purchaseOption,
      release_clause: releaseClause,
      renewal_option: renewalOption,
      agent_name: agentName,
      notes,
    };

    setSubmitting(true);
    try {
      if (isEdit) {
        await api(`/contracts/${contract!.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      } else {
        await api(`/contracts`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
      }
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error al guardar");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.formGrid}>
        <label className={styles.field}>
          <span className={styles.label}>Tipo</span>
          <select value={contractType} onChange={(e) => setContractType(e.target.value as ContractType)}>
            <option value="permanent">Permanente</option>
            <option value="loan_in">Préstamo (entra)</option>
            <option value="loan_out">Préstamo (cedido)</option>
            <option value="youth">Cantera</option>
          </select>
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Inicio contrato</span>
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} required />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Fin contrato</span>
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} required />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Fecha de firma (opc.)</span>
          <input type="date" value={signingDate} onChange={(e) => setSigningDate(e.target.value)} />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Porcentaje contrato</span>
          <input
            type="number"
            step="0.01"
            min="0"
            max="1"
            value={ownership}
            onChange={(e) => setOwnership(e.target.value)}
          />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Total bruto</span>
          <input
            type="number"
            step="any"
            value={totalGross}
            onChange={(e) => setTotalGross(e.target.value)}
            placeholder="50000000"
          />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Moneda</span>
          <select value={currency} onChange={(e) => setCurrency(e.target.value)}>
            <option value="CLP">CLP</option>
            <option value="USD">USD</option>
            <option value="EUR">EUR</option>
            <option value="ARS">ARS</option>
          </select>
        </label>
        <label className={`${styles.field} ${styles.fullWidth}`}>
          <span className={styles.label}>Bono fijo</span>
          <textarea value={fixedBonus} onChange={(e) => setFixedBonus(e.target.value)} placeholder="NO o descripción" />
        </label>
        <label className={`${styles.field} ${styles.fullWidth}`}>
          <span className={styles.label}>Bono variable</span>
          <textarea value={variableBonus} onChange={(e) => setVariableBonus(e.target.value)} placeholder="NO o descripción" />
        </label>
        <label className={`${styles.field} ${styles.fullWidth}`}>
          <span className={styles.label}>Aumento</span>
          <textarea value={salaryIncrease} onChange={(e) => setSalaryIncrease(e.target.value)} placeholder="NO o descripción" />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Opción compra</span>
          <input value={purchaseOption} onChange={(e) => setPurchaseOption(e.target.value)} placeholder="NO o monto" />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Cláusula salida</span>
          <input value={releaseClause} onChange={(e) => setReleaseClause(e.target.value)} placeholder="NO o monto" />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Opción renovación</span>
          <input value={renewalOption} onChange={(e) => setRenewalOption(e.target.value)} placeholder="NO / SI / condiciones" />
        </label>
        <label className={styles.field}>
          <span className={styles.label}>Agente / representante</span>
          <input value={agentName} onChange={(e) => setAgentName(e.target.value)} />
        </label>
        <label className={`${styles.field} ${styles.fullWidth}`}>
          <span className={styles.label}>Notas internas</span>
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.formActions}>
        <button type="button" className={styles.cancelBtn} onClick={onCancel} disabled={submitting}>
          Cancelar
        </button>
        <button type="submit" className={styles.saveBtn} disabled={submitting}>
          {submitting ? "Guardando…" : isEdit ? "Guardar cambios" : "Crear contrato"}
        </button>
      </div>
    </form>
  );
}
