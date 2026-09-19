"""Pure external-action eligibility reducer."""
from .models import ActionContext, EligibilityResult, Permission


def eligibility(
    context: ActionContext,
    permission: Permission,
    *,
    reviewed_revision: int | None = None,
) -> EligibilityResult:
    reasons: list[str] = []
    if not context.selected_finalized:
        reasons.append("event_not_selected_and_finalized")
    if context.machine_decision != "supported":
        reasons.append("event_not_supported")
    if context.run_mode != "normal":
        reasons.append("run_mode_forbids_delivery")
    if context.deleted or context.cancelled:
        reasons.append("event_unavailable")
    if not context.budget_available:
        reasons.append("budget_unavailable")
    if not context.explicitly_enabled:
        reasons.append("action_not_explicitly_enabled")
    if context.action_ref != permission.id:
        reasons.append("authorization_reference_mismatch")
    if context.workspace_id != permission.workspace_id:
        reasons.append("authorization_workspace_mismatch")
    if not permission.enabled:
        reasons.append("permission_revoked")
    if context.human_review == "dismissed_by_user":
        reasons.append("event_dismissed")
    elif context.human_review != "confirmed_by_user" and not permission.preapproved:
        reasons.append("human_review_required")
    if reviewed_revision is not None and reviewed_revision != context.event_revision:
        reasons.append("stale_review_revision")
    return EligibilityResult(not reasons, tuple(reasons))
