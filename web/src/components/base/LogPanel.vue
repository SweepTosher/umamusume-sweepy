<template>
  <div>
    <div class="card">
      <div class="card-body">
        <div class="d-flex align-items-center mb-3" style="gap:12px">
          <h5 class="mb-0">Runtime Logs</h5>
          <div class="ml-auto"></div>
          <button @click="toggleAutoLog" class="btn btn-sm" :class="autoLog ? 'btn--primary' : 'btn--outline'">
            <font-awesome-icon :icon="autoLog ? 'fa-regular fa-circle-play' : 'fa-regular fa-circle-pause'" />
            <span>Auto-refresh: {{ autoLog ? 'ON' : 'OFF' }}</span>
          </button>
        </div>
        <div class="crt-slab">
          <textarea id="scroll_text" disabled :placeholder="logContent" class="form-control crt-text log-textarea" aria-label="With textarea">{{logContent}}</textarea>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: "LogPanel",
  props: ['logContent', 'autoLog', 'toggleAutoLog'],
  data(){
    return{ autoScroll: true }
  },
  updated(){
    if (this.autoScroll){
      const textarea = document.getElementById('scroll_text');
      textarea.scrollTop = textarea.scrollHeight;
    }
  }
}
</script>

<style scoped>
textarea{min-height:600px;font-size:12px;line-height:1.35}
.form-control:disabled{background:var(--surface-2)}
.card{display:block}
.card-body{display:block}
.crt-slab{position:relative;border-radius:12px;overflow:hidden;padding:8px}
.crt-slab:before{content:"";position:absolute;inset:0;background:repeating-linear-gradient(0deg, rgba(255,255,255,.05) 0, rgba(255,255,255,.05) 1px, transparent 2px, transparent 4px);opacity:.08;pointer-events:none}
.crt-slab:after{content:"";position:absolute;inset:0;background:radial-gradient(120% 80% at 50% 0%, color-mix(in srgb, var(--accent) 18%, transparent), transparent 60%);mix-blend-mode:screen;opacity:.3;pointer-events:none}
.crt-text{font-family:'Share Tech Mono',ui-monospace,Consolas,Monaco,monospace;color:#E6E6E6;text-shadow:0 0 6px color-mix(in srgb, var(--accent) 25%, transparent)}
.log-textarea{display:block;width:100%;min-height:70vh;border:1px solid var(--accent);border-radius:var(--radius-sm);color:var(--muted);box-shadow:inset 0 0 0 1px rgba(255,255,255,.06)}
</style>