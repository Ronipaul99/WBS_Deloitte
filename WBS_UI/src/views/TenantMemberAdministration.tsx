import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  LoaderCircle,
  MailPlus,
  RefreshCw,
  Search,
  ShieldAlert,
  Trash2,
  UserPlus,
  UsersRound,
  X,
} from 'lucide-react';
import { ApiError } from '../services/apiClient';
import {
  getTenantMembers,
  inviteTenantMember,
  removeTenantMember,
  resendTenantInvitation,
  revokeTenantInvitation,
  updateTenantMemberRole,
} from '../services/memberAdministration';
import type {
  MemberListResponse,
  MembershipRole,
  TenantInvitation,
  TenantMember,
} from '../services/memberAdministration';
import './TenantMemberAdministration.css';

const PAGE_SIZE = 10;
const EMPTY_DATA: MemberListResponse = {
  members: [],
  invitations: [],
  total_members: 0,
  total_invitations: 0,
  offset: 0,
  limit: PAGE_SIZE,
};

interface TenantMemberAdministrationProps {
  tenantId: string;
  tenantName: string;
  currentUserId: string;
  canInvite: boolean;
  canUpdate: boolean;
  canRemove: boolean;
  onCurrentMembershipChanged: () => Promise<void>;
}

type ConfirmationTarget =
  | { kind: 'member'; item: TenantMember }
  | { kind: 'invitation'; item: TenantInvitation };

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Unavailable';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(date);
}

function roleLabel(role: MembershipRole): string {
  return role.charAt(0) + role.slice(1).toLowerCase();
}

function safeMutationError(reason: unknown): string {
  if (reason instanceof ApiError && reason.status === 409) return reason.message;
  if (reason instanceof ApiError && reason.status === 429) {
    return 'Invitation delivery is temporarily limited. Try again later.';
  }
  if (reason instanceof ApiError && reason.status === 404) {
    return 'That record is no longer available. The list has been refreshed.';
  }
  return 'The change could not be completed. Please try again.';
}

export default function TenantMemberAdministration({
  tenantId,
  tenantName,
  currentUserId,
  canInvite,
  canUpdate,
  canRemove,
  onCurrentMembershipChanged,
}: TenantMemberAdministrationProps) {
  const [data, setData] = useState<MemberListResponse>(EMPTY_DATA);
  const [state, setState] = useState<'loading' | 'ready' | 'error' | 'denied'>('loading');
  const [draftSearch, setDraftSearch] = useState('');
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState('');
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<MembershipRole>('VIEWER');
  const [confirmation, setConfirmation] = useState<ConfirmationTarget | null>(null);
  const inviteEmailRef = useRef<HTMLInputElement>(null);
  const cancelConfirmationRef = useRef<HTMLButtonElement>(null);

  const load = useCallback(async () => {
    setState('loading');
    setError('');
    try {
      setData(await getTenantMembers(tenantId, search, offset, PAGE_SIZE));
      setState('ready');
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 403) {
        setState('denied');
      } else if (!(reason instanceof ApiError && reason.status === 401)) {
        setError('Workspace members could not be loaded.');
        setState('error');
      }
    }
  }, [offset, search, tenantId]);

  useEffect(() => {
    let active = true;
    void getTenantMembers(tenantId, search, offset, PAGE_SIZE)
      .then((response) => {
        if (!active) return;
        setData(response);
        setState('ready');
      })
      .catch((reason: unknown) => {
        if (!active || (reason instanceof ApiError && reason.status === 401)) return;
        if (reason instanceof ApiError && reason.status === 403) {
          setState('denied');
        } else {
          setError('Workspace members could not be loaded.');
          setState('error');
        }
      });
    return () => { active = false; };
  }, [offset, search, tenantId]);

  useEffect(() => {
    if (!inviteOpen) return;
    inviteEmailRef.current?.focus();
  }, [inviteOpen]);

  useEffect(() => {
    if (!confirmation) return;
    cancelConfirmationRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busyId) setConfirmation(null);
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [busyId, confirmation]);

  const pageNumber = Math.floor(offset / PAGE_SIZE) + 1;
  const totalRows = Math.max(data.total_members, data.total_invitations);
  const totalPages = Math.max(1, Math.ceil(totalRows / PAGE_SIZE));
  const applySearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextSearch = draftSearch.trim();
    setState('loading');
    setError('');
    if (nextSearch === search && offset === 0) {
      void load();
      return;
    }
    setOffset(0);
    setSearch(nextSearch);
  };

  const submitInvitation = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusyId('invite');
    setError('');
    try {
      await inviteTenantMember(tenantId, inviteEmail.trim(), inviteRole);
      setInviteOpen(false);
      setInviteEmail('');
      setInviteRole('VIEWER');
      if (offset === 0) {
        await load();
      } else {
        setState('loading');
        setOffset(0);
      }
    } catch (reason) {
      setError(safeMutationError(reason));
    } finally {
      setBusyId('');
    }
  };

  const changeRole = async (member: TenantMember, role: MembershipRole) => {
    if (member.role === role) return;
    setBusyId(member.user_id);
    setError('');
    try {
      const updated = await updateTenantMemberRole(tenantId, member.user_id, role);
      setData((current) => ({
        ...current,
        members: current.members.map((item) => (
          item.user_id === updated.user_id ? updated : item
        )),
      }));
      if (member.user_id === currentUserId) await onCurrentMembershipChanged();
    } catch (reason) {
      setError(safeMutationError(reason));
    } finally {
      setBusyId('');
    }
  };

  const resend = async (invitation: TenantInvitation) => {
    setBusyId(invitation.id);
    setError('');
    try {
      const updated = await resendTenantInvitation(tenantId, invitation.id);
      setData((current) => ({
        ...current,
        invitations: current.invitations.map((item) => (
          item.id === updated.id ? updated : item
        )),
      }));
    } catch (reason) {
      setError(safeMutationError(reason));
      if (reason instanceof ApiError && reason.status === 404) await load();
    } finally {
      setBusyId('');
    }
  };

  const confirmDestructiveAction = async () => {
    if (!confirmation) return;
    const target = confirmation;
    setBusyId(target.kind === 'member' ? target.item.user_id : target.item.id);
    setError('');
    try {
      if (target.kind === 'member') {
        await removeTenantMember(tenantId, target.item.user_id);
        setData((current) => ({
          ...current,
          members: current.members.filter((item) => item.user_id !== target.item.user_id),
          total_members: Math.max(0, current.total_members - 1),
        }));
        setConfirmation(null);
        if (target.item.user_id === currentUserId) await onCurrentMembershipChanged();
      } else {
        await revokeTenantInvitation(tenantId, target.item.id);
        setData((current) => ({
          ...current,
          invitations: current.invitations.filter((item) => item.id !== target.item.id),
          total_invitations: Math.max(0, current.total_invitations - 1),
        }));
        setConfirmation(null);
      }
    } catch (reason) {
      setError(safeMutationError(reason));
      setConfirmation(null);
      if (reason instanceof ApiError && reason.status === 404) await load();
    } finally {
      setBusyId('');
    }
  };

  if (state === 'denied') {
    return (
      <section className="member-admin-denied" role="alert">
        <ShieldAlert size={28} />
        <h2>Access denied</h2>
        <p>You do not have permission to manage workspace members.</p>
      </section>
    );
  }

  return (
    <section className="member-admin" aria-labelledby="member-admin-title">
      <div className="member-admin-heading">
        <UsersRound size={20} />
        <div>
          <h2 id="member-admin-title">Workspace members</h2>
          <p>Manage access to {tenantName}.</p>
        </div>
        {canInvite && (
          <button type="button" className="member-admin-primary" onClick={() => setInviteOpen(true)}>
            <UserPlus size={16} /> Invite member
          </button>
        )}
      </div>

      <div className="member-admin-toolbar">
        <form onSubmit={applySearch} role="search">
          <Search size={16} />
          <input
            aria-label="Search members and invitations"
            value={draftSearch}
            onChange={(event) => setDraftSearch(event.target.value)}
            placeholder="Search name or email"
          />
          <button type="submit">Search</button>
        </form>
        <button type="button" className="member-admin-icon-button" onClick={() => void load()} title="Refresh list" aria-label="Refresh member list">
          <RefreshCw size={17} />
        </button>
      </div>

      {error && state === 'ready' && !inviteOpen && (
        <p className="member-admin-error" role="alert">{error}</p>
      )}

      {state === 'loading' && (
        <div className="member-admin-state" role="status">
          <LoaderCircle className="member-admin-spinner" size={20} /> Loading workspace members...
        </div>
      )}
      {state === 'error' && (
        <div className="member-admin-state member-admin-state--error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => void load()}>Retry</button>
        </div>
      )}

      {state === 'ready' && (
        <>
          <div className="member-admin-table-section">
            <div className="member-admin-table-title">
              <h3>Members</h3><span>{data.total_members}</span>
            </div>
            {data.members.length ? (
              <div className="member-admin-table-wrap">
                <table>
                  <thead><tr><th>Member</th><th>Status</th><th>Role</th><th><span className="member-admin-sr-only">Actions</span></th></tr></thead>
                  <tbody>
                    {data.members.map((member) => {
                      return (
                        <tr key={member.user_id}>
                          <td data-label="Member">
                            <strong>{member.display_name}</strong>
                            <small>{member.email}</small>
                            {member.user_id === currentUserId && <span className="member-admin-you">You</span>}
                          </td>
                          <td data-label="Status"><span className={`member-admin-status member-admin-status--${member.status.toLowerCase()}`}>{member.status.toLowerCase()}</span></td>
                          <td data-label="Role">
                            <select
                              aria-label={`Role for ${member.display_name}`}
                              value={member.role}
                              disabled={!canUpdate || busyId === member.user_id}
                              onChange={(event) => void changeRole(member, event.target.value as MembershipRole)}
                            >
                              <option value="ADMIN">Administrator</option>
                              <option value="EDITOR">Editor</option>
                              <option value="VIEWER">Viewer</option>
                            </select>
                          </td>
                          <td>
                            {canRemove && (
                              <button
                                type="button"
                                className="member-admin-icon-button member-admin-remove"
                                disabled={busyId === member.user_id}
                                onClick={() => setConfirmation({ kind: 'member', item: member })}
                                aria-label={`Remove ${member.display_name}`}
                                title="Remove member"
                              >
                                <Trash2 size={16} />
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : <div className="member-admin-empty">No members match this search.</div>}
          </div>

          <div className="member-admin-table-section">
            <div className="member-admin-table-title">
              <h3>Pending invitations</h3><span>{data.total_invitations}</span>
            </div>
            {data.invitations.length ? (
              <div className="member-admin-table-wrap">
                <table>
                  <thead><tr><th>Email</th><th>Expires</th><th>Role</th><th><span className="member-admin-sr-only">Actions</span></th></tr></thead>
                  <tbody>
                    {data.invitations.map((invitation) => (
                      <tr key={invitation.id}>
                        <td data-label="Email"><strong>{invitation.email}</strong><small>Pending</small></td>
                        <td data-label="Expires">{formatDate(invitation.expires_at)}</td>
                        <td data-label="Role">{roleLabel(invitation.role)}</td>
                        <td className="member-admin-row-actions">
                          {canInvite && (
                            <>
                              <button type="button" className="member-admin-icon-button" disabled={busyId === invitation.id} onClick={() => void resend(invitation)} aria-label={`Resend invitation to ${invitation.email}`} title="Resend invitation"><MailPlus size={16} /></button>
                              <button type="button" className="member-admin-icon-button member-admin-remove" disabled={busyId === invitation.id} onClick={() => setConfirmation({ kind: 'invitation', item: invitation })} aria-label={`Revoke invitation for ${invitation.email}`} title="Revoke invitation"><Trash2 size={16} /></button>
                            </>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <div className="member-admin-empty">No pending invitations.</div>}
          </div>

          {totalPages > 1 && (
            <nav className="member-admin-pagination" aria-label="Member pages">
              <button type="button" className="member-admin-icon-button" disabled={offset === 0} onClick={() => { setState('loading'); setOffset(Math.max(0, offset - PAGE_SIZE)); }} aria-label="Previous page" title="Previous page"><ChevronLeft size={17} /></button>
              <span>Page {pageNumber} of {totalPages}</span>
              <button type="button" className="member-admin-icon-button" disabled={pageNumber >= totalPages} onClick={() => { setState('loading'); setOffset(offset + PAGE_SIZE); }} aria-label="Next page" title="Next page"><ChevronRight size={17} /></button>
            </nav>
          )}
        </>
      )}

      {inviteOpen && (
        <div className="member-admin-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busyId) setInviteOpen(false); }}>
          <section className="member-admin-dialog" role="dialog" aria-modal="true" aria-labelledby="invite-member-title">
            <div className="member-admin-dialog-heading">
              <div><UserPlus size={18} /><h3 id="invite-member-title">Invite member</h3></div>
              <button type="button" className="member-admin-icon-button" onClick={() => setInviteOpen(false)} aria-label="Close invitation" title="Close"><X size={17} /></button>
            </div>
            <form onSubmit={submitInvitation}>
              <label htmlFor="member-invite-email">Email address<input ref={inviteEmailRef} id="member-invite-email" type="email" value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} autoComplete="email" disabled={busyId === 'invite'} required /></label>
              <label htmlFor="member-invite-role">Workspace role<select id="member-invite-role" value={inviteRole} onChange={(event) => setInviteRole(event.target.value as MembershipRole)} disabled={busyId === 'invite'}><option value="VIEWER">Viewer</option><option value="EDITOR">Editor</option><option value="ADMIN">Administrator</option></select></label>
              {error && <p className="member-admin-error member-admin-dialog-error" role="alert">{error}</p>}
              <div className="member-admin-dialog-actions">
                <button type="button" className="member-admin-secondary" onClick={() => setInviteOpen(false)} disabled={busyId === 'invite'}>Cancel</button>
                <button type="submit" className="member-admin-primary" disabled={busyId === 'invite' || !inviteEmail.trim()}>{busyId === 'invite' && <LoaderCircle className="member-admin-spinner" size={16} />}{busyId === 'invite' ? 'Sending...' : 'Send invitation'}</button>
              </div>
            </form>
          </section>
        </div>
      )}

      {confirmation && (
        <div className="member-admin-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !busyId) setConfirmation(null); }}>
          <section className="member-admin-dialog" role="dialog" aria-modal="true" aria-labelledby="member-confirmation-title">
            <div className="member-admin-confirmation-heading">
              <span><AlertTriangle size={18} /></span>
              <div>
                <h3 id="member-confirmation-title">{confirmation.kind === 'member' ? 'Remove this member?' : 'Revoke this invitation?'}</h3>
                <p>{confirmation.kind === 'member' ? `${confirmation.item.display_name} will immediately lose access to this workspace.` : `${confirmation.item.email} will no longer be able to use this invitation.`}</p>
              </div>
            </div>
            <div className="member-admin-dialog-actions">
              <button ref={cancelConfirmationRef} type="button" className="member-admin-secondary" onClick={() => setConfirmation(null)} disabled={Boolean(busyId)}>Cancel</button>
              <button type="button" className="member-admin-danger" onClick={() => void confirmDestructiveAction()} disabled={Boolean(busyId)}>{busyId && <LoaderCircle className="member-admin-spinner" size={16} />}{confirmation.kind === 'member' ? 'Remove member' : 'Revoke invitation'}</button>
            </div>
          </section>
        </div>
      )}
    </section>
  );
}
