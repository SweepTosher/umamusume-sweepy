<template>
  <div v-if="show" class="modal-overlay" @click="handleOverlayClick">
    <div class="modal-dialog" @click.stop>
      <div class="modal-content notification-dialog">
        <div class="modal-header">
          <h5 class="modal-title">
            <i class="fas fa-tools"></i>
            Manual Skill Purchase Required
          </h5>
          <button type="button" class="btn-close" @click="handleCancel" aria-label="Close"></button>
        </div>
        <div class="modal-body">
          <div class="notification-content">
            <div class="notification-icon">
              <i class="fas fa-hand-paper"></i>
            </div>
            <div class="notification-text">
              <p class="notification-message">
                Please learn skills manually in the game, then press the <strong>Confirm</strong> button when you're done.
              </p>
              <p class="notification-hint">
                The bot will continue automatically after you complete the skill purchase.
              </p>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="handleCancel">
            Cancel
          </button>
          <button type="button" class="btn btn-primary" @click="handleConfirm">
            I'm Done - Continue
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'ManualSkillNotificationModal',
  props: {
    show: {
      type: Boolean,
      default: false
    }
  },
  emits: ['update:show', 'confirm', 'cancel'],
  methods: {
    handleConfirm() {
      this.$emit('confirm');
      this.$emit('update:show', false);
    },
    handleCancel() {
      this.$emit('cancel');
      this.$emit('update:show', false);
    },
    handleOverlayClick() {
      // Don't close when clicking overlay - require explicit button click
    }
  }
};
</script>

<style scoped>
.modal-overlay {position:fixed;top:0;left:0;width:100%;height:100%;background-color: rgba(0, 0, 0, 0.5);display:flex;align-items:center;justify-content:center;z-index:9999}
.modal-dialog {max-width:500px;width:90%;margin:0}
.notification-dialog {border-radius:12px;border:none;box-shadow: var(--elev);background:linear-gradient(180deg,rgba(255,255,255,.02),rgba(255,255,255,.01)) , linear-gradient(180deg,var(--panel),var(--panel-2));color:var(--text)}
.notification-dialog .modal-header {background: linear-gradient(135deg, var(--primary) 0%, var(--primary-2) 100%);color:#fff;border-radius:12px 12px 0 0;border:none;padding:1.5rem}
.notification-dialog .modal-title {font-size:1.25rem;font-weight:600;margin:0}
.notification-dialog .modal-title i {margin-right:.5rem;color:#ffd700}
.notification-dialog .btn-close {filter: invert(1);opacity:.8}
.notification-dialog .btn-close:hover {opacity:1}
.notification-dialog .modal-body {padding:2rem;background: transparent}
.notification-content {display:flex;align-items:flex-start;gap:1.5rem}
.notification-icon {flex-shrink:0;width:60px;height:60px;background: linear-gradient(135deg, var(--accent), var(--accent-2));border-radius:50%;display:flex;align-items:center;justify-content:center;color:white;font-size:1.5rem;box-shadow:0 4px 15px rgba(255,45,163,.35)}
.notification-text {flex:1}
.notification-message {font-size:1.1rem;color:var(--text);margin-bottom:1rem;line-height:1.5}
.notification-hint {font-size:.95rem;color:var(--muted);margin:0;font-style:italic}
.notification-dialog .modal-footer {background: transparent;border-top: 1px solid rgba(255,255,255,.06);padding:1.5rem;border-radius:0 0 12px 12px;display:flex;justify-content:flex-end;gap:.75rem}
.notification-dialog .btn {padding:.75rem 1.5rem;font-weight:500;border-radius:8px;border:none;transition:all .2s ease}
.notification-dialog .btn-secondary {background:#1b2332;color:white}
.notification-dialog .btn-secondary:hover {background:#1f2940;transform: translateY(-1px)}
.notification-dialog .btn-primary {background: linear-gradient(135deg, var(--primary) 0%, var(--primary-2) 100%);color:white}
.notification-dialog .btn-primary:hover {filter:saturate(115%);transform: translateY(-1px);box-shadow:0 4px 12px rgba(109,94,245,.35)}
#manual-skill-notification-modal.modal {z-index:1070}
#manual-skill-notification-modal .modal-dialog {z-index:1071}
@keyframes pulse {0%{transform:scale(1)}50%{transform:scale(1.05)}100%{transform:scale(1)}}
@media (max-width: 576px) {.notification-content{flex-direction:column;text-align:center}.notification-icon{align-self:center}}
</style> 