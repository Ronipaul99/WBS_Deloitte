import { useEffect, useId, useRef, type ReactNode, type RefObject } from 'react';
import { X } from 'lucide-react';
import './WorkflowSurfaces.css';

interface Props {
  title: string;
  description: string;
  eyebrow: string;
  icon: ReactNode;
  children: ReactNode;
  footer: ReactNode;
  busy?: boolean;
  tone?: 'blue' | 'success';
  returnFocusRef?: RefObject<HTMLElement | null>;
  onClose: () => void;
}

export default function WorkflowDialog({ title, description, eyebrow, icon, children, footer,
  busy = false, tone = 'blue', onClose, returnFocusRef }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const previous = returnFocusRef?.current
      ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    const overflow = document.body.style.overflow;
    dialog.showModal();
    document.body.style.overflow = 'hidden';
    dialog.querySelector<HTMLElement>('[data-dialog-focus]')?.focus();
    return () => {
      dialog.close();
      document.body.style.overflow = overflow;
      if (previous?.isConnected) previous.focus();
    };
  }, [returnFocusRef]);

  return (
    <dialog ref={ref} className={`workflow-dialog workflow-tone-${tone}`}
      tabIndex={-1}
      aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`} aria-modal="true"
      aria-busy={busy}
      onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}
      onKeyDown={(event) => {
        if (event.key !== 'Tab') return;
        const elements = [...event.currentTarget.querySelectorAll<HTMLElement>(
          'button, a[href], input, select, textarea, [tabindex]',
        )].filter((element) => element.tabIndex >= 0 && !element.matches(':disabled')
          && element.getClientRects().length > 0);
        const first = elements[0];
        const last = elements[elements.length - 1];
        if (!first) { event.preventDefault(); event.currentTarget.focus(); return; }
        if (event.shiftKey && (document.activeElement === first || document.activeElement === event.currentTarget)) {
          event.preventDefault(); last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || document.activeElement === event.currentTarget)) {
          event.preventDefault(); first.focus();
        }
      }}
      onClick={(event) => {
        if (event.target !== event.currentTarget || busy) return;
        const box = event.currentTarget.getBoundingClientRect();
        if (event.clientX < box.left || event.clientX > box.right
          || event.clientY < box.top || event.clientY > box.bottom) onClose();
      }}>
      <div className="workflow-dialog-heading">
        <span className="workflow-hero-icon" aria-hidden="true">{icon}</span>
        <button type="button" className="workflow-close" aria-label="Close dialog"
          onClick={onClose} disabled={busy}><X size={19} aria-hidden="true" /></button>
        <p className="workflow-eyebrow">{eyebrow}</p>
        <h2 id={`${id}-title`}>{title}</h2>
        <p id={`${id}-description`} className="workflow-description">{description}</p>
      </div>
      <div className="workflow-dialog-content">{children}</div>
      <div className="workflow-dialog-footer">{footer}</div>
    </dialog>
  );
}
