<template>
  <div>
    <div class="card">
      <div class="card-body">
        <div class="d-flex align-items-center mb-3 gap-12px">
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
    },
  }
</script>