import { useState } from "react";
import { Link } from "react-router-dom";

import { useUser } from "../auth/context";
import { hasRole } from "../auth/user";
import { useLiveMessage } from "../live/context";

interface Toast {
  id: string;
  text: string;
  link?: { to: string; label: string };
}

const MAX_TOASTS = 3;

/** Short notices for live messages. The full detail is always one click away. */
export function Toasts() {
  const user = useUser();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const reviews = hasRole(user, "reviewer", "admin");

  useLiveMessage((m) => {
    let toast: Toast | null = null;
    if (m.type === "alert.created") {
      toast = {
        id: m.alert_id,
        text: m.message,
        link: { to: `/people/${encodeURIComponent(m.subject_id)}`, label: "View timeline" },
      };
    } else if (m.type === "review.created" && reviews) {
      toast = { id: m.review_id, text: "A new item is waiting for review." };
    }
    if (toast) {
      const next = toast;
      setToasts((list) => [next, ...list.filter((t) => t.id !== next.id)].slice(0, MAX_TOASTS));
    }
  });

  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <div key={toast.id} className="toast">
          <p>{toast.text}</p>
          <div className="toast-actions">
            {toast.link && <Link to={toast.link.to}>{toast.link.label}</Link>}
            <button
              type="button"
              className="link"
              onClick={() => setToasts((list) => list.filter((t) => t.id !== toast.id))}
            >
              Dismiss
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
