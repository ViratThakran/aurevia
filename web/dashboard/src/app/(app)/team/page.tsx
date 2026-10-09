"use client";

import { useState } from "react";

import {
  Alert,
  Button,
  Card,
  Field,
  Input,
  Loading,
  PageHeader,
  Select,
  Table,
  formatDate,
} from "@/components/ui";
import { api, type Schemas } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { PERMISSIONS } from "@/lib/types";

type Role = Schemas["CustomRoleResponse"];

/** "owner" | "admin" | "member" | "custom:<id>" */
function roleValue(role: string, customRoleId?: string | null): string {
  return customRoleId ? `custom:${customRoleId}` : role;
}

function splitRole(value: string): { role: string; custom_role_id: string | null } {
  return value.startsWith("custom:")
    ? { role: "member", custom_role_id: value.slice(7) }
    : { role: value, custom_role_id: null };
}

function RoleSelect({ value, onChange, roles, isOwner }: { value: string; onChange: (v: string) => void; roles: Role[]; isOwner: boolean }) {
  return (
    <Select value={value} onChange={(e) => onChange(e.target.value)}>
      {isOwner ? <option value="owner">Owner</option> : null}
      <option value="admin">Admin</option>
      <option value="member">Member</option>
      {roles.map((r) => (
        <option key={r.id} value={`custom:${r.id}`}>{r.name}</option>
      ))}
    </Select>
  );
}

function Members({ roles }: { roles: Role[] }) {
  const { me, can } = useSession();
  const members = useApi<Schemas["MemberResponse"][]>("/tenant/members");
  const { run, error, pending } = useAction();
  const manage = can("team.manage");
  const isOwner = me?.role === "owner";
  return (
    <Card title="Members">
      <Alert>{error}</Alert>
      {members.data ? (
        <Table
          head={["Name", "Email", "Role", "Joined", ""]}
          rows={members.data.map((m) => {
            const self = m.user_id === me?.user_id;
            return [
              m.full_name ?? "—",
              m.email,
              manage && !self ? (
                <RoleSelect
                  key="r"
                  roles={roles}
                  isOwner={isOwner}
                  value={roleValue(m.role, m.custom_role_id)}
                  onChange={async (value) => {
                    if (await run(() => api(`/tenant/members/${m.membership_id}`, { method: "PATCH", body: splitRole(value) }).then(() => true)))
                      void members.reload();
                  }}
                />
              ) : (
                m.custom_role_id ? roles.find((r) => r.id === m.custom_role_id)?.name ?? "custom" : m.role
              ),
              formatDate(m.joined_at, false),
              manage && !self ? (
                <Button key="x" variant="ghost" pending={pending} onClick={async () => {
                  if (!window.confirm(`Remove ${m.email}? They are signed out at once.`)) return;
                  if (await run(() => api(`/tenant/members/${m.membership_id}`, { method: "DELETE" }).then(() => true)))
                    void members.reload();
                }}>Remove</Button>
              ) : null,
            ];
          })}
        />
      ) : <Loading />}
    </Card>
  );
}

function Invitations({ roles }: { roles: Role[] }) {
  const { me } = useSession();
  const invitations = useApi<Schemas["InvitationResponse"][]>("/team/invitations");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("member");
  const [link, setLink] = useState<string | null>(null);
  const { run, error, pending } = useAction();
  return (
    <Card title="Invitations">
      <form
        className="mb-4 flex flex-wrap items-end gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          const created = await run(() =>
            api<Schemas["InvitationCreated"]>("/team/invitations", { method: "POST", body: { email, ...splitRole(role) } }),
          );
          if (created) {
            setLink(`${window.location.origin}/invite?token=${encodeURIComponent(created.token)}`);
            setEmail("");
            void invitations.reload();
          }
        }}
      >
        <Field label="Email"><Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Role"><RoleSelect value={role} onChange={setRole} roles={roles} isOwner={me?.role === "owner"} /></Field>
        <Button type="submit" pending={pending}>Create invitation</Button>
      </form>
      <Alert>{error}</Alert>
      {link ? (
        <div className="mb-4 space-y-2">
          <Alert tone="good">
            Send this link to them yourself. It is shown only now and works for 7 days.
          </Alert>
          <div className="flex gap-2">
            <Input readOnly value={link} onFocus={(e) => e.target.select()} />
            <Button variant="secondary" onClick={() => void navigator.clipboard.writeText(link)}>Copy</Button>
          </div>
        </div>
      ) : null}
      <Table
        head={["Email", "Role", "Expires", ""]}
        rows={(invitations.data ?? []).map((i) => [
          i.email,
          i.custom_role_id ? roles.find((r) => r.id === i.custom_role_id)?.name ?? "custom" : i.role,
          formatDate(i.expires_at),
          <Button key="x" variant="ghost" onClick={async () => {
            if (await run(() => api(`/team/invitations/${i.id}`, { method: "DELETE" }).then(() => true))) void invitations.reload();
          }}>Revoke</Button>,
        ])}
        empty="No pending invitations."
      />
    </Card>
  );
}

function Roles({ roles, reload }: { roles: Role[]; reload: () => void }) {
  const { me } = useSession();
  const [editing, setEditing] = useState<Role | "new" | null>(null);
  const [name, setName] = useState("");
  const [perms, setPerms] = useState<Set<string>>(new Set());
  const { run, error, pending } = useAction();
  const mine = new Set(me?.permissions ?? []);

  function open(role: Role | "new") {
    setEditing(role);
    setName(role === "new" ? "" : role.name);
    setPerms(new Set(role === "new" ? [] : role.permissions));
  }

  return (
    <Card title="Custom roles" actions={<Button variant="secondary" onClick={() => open("new")}>New role</Button>}>
      <Table
        head={["Role", "Can", ""]}
        rows={roles.map((r) => [
          r.name,
          <span key="p" className="text-xs text-muted">{r.permissions.join(", ")}</span>,
          <div key="a" className="flex gap-1">
            <Button variant="ghost" onClick={() => open(r)}>Edit</Button>
            <Button variant="ghost" onClick={async () => {
              if (await run(() => api(`/team/roles/${r.id}`, { method: "DELETE" }).then(() => true))) reload();
            }}>Delete</Button>
          </div>,
        ])}
        empty="Owners and admins can do everything; members can call, manage leads and see analytics. Make a custom role for anything in between."
      />
      {editing ? (
        <form
          className="mt-4 space-y-3 rounded-md border border-border p-4"
          onSubmit={async (e) => {
            e.preventDefault();
            const body = { name, permissions: [...perms] };
            const saved = await run(() =>
              editing === "new"
                ? api("/team/roles", { method: "POST", body })
                : api(`/team/roles/${editing.id}`, { method: "PATCH", body }),
            );
            if (saved) {
              setEditing(null);
              reload();
            }
          }}
        >
          <Field label="Name"><Input required value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <div className="grid gap-2 sm:grid-cols-2">
            {PERMISSIONS.map(([key, text]) => (
              <label key={key} className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  disabled={!mine.has(key)}
                  checked={perms.has(key)}
                  onChange={(e) => {
                    const next = new Set(perms);
                    if (e.target.checked) next.add(key);
                    else next.delete(key);
                    setPerms(next);
                  }}
                />
                <span>{text}<span className="block text-xs text-muted">{key}</span></span>
              </label>
            ))}
          </div>
          <p className="text-xs text-muted">You can only grant permissions you hold yourself.</p>
          <div className="flex gap-2">
            <Button type="submit" pending={pending} disabled={perms.size === 0}>Save role</Button>
            <Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
          </div>
        </form>
      ) : null}
      <Alert>{error}</Alert>
    </Card>
  );
}

export default function TeamPage() {
  const { can } = useSession();
  const roles = useApi<Role[]>(can("team.manage") ? "/team/roles" : null);
  const list = roles.data ?? [];
  return (
    <>
      <PageHeader title="Team" description="Who can use this workspace and what each person may do." />
      <div className="grid gap-6">
        <Members roles={list} />
        {can("team.manage") ? (
          <>
            <Invitations roles={list} />
            <Roles roles={list} reload={() => void roles.reload()} />
          </>
        ) : null}
      </div>
    </>
  );
}
