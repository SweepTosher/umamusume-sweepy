<template>
  <div class="list-panel">
    <div class="mb-3">
      <auto-status-panel></auto-status-panel>
    </div>
    <div class="mb-3">
      <running-task-panel :running-task="runningTask"></running-task-panel>
    </div>
    <div class="mb-3">
      <waiting-task-list :waiting-task-list="waitingTaskList"></waiting-task-list>
    </div>
    <div class="mb-3">
      <history-task-list :history-task-list="historyTaskList"></history-task-list>
    </div>
    <div class="mb-3">
      <div class="card image-card">
        <div class="card-body">
          <div class="image-layer" :style="{ '--image-url': `url(${imageBg})` }" @click="toggleCharacter"></div>
        </div>
      </div>
    </div>
    <div>
      <task-edit-modal></task-edit-modal>
    </div>
  </div>
</template>

<script>
import RunningTaskPanel from "@/components/RunningTaskPanel.vue";
import WaitingTaskList from "@/components/WaitingTaskList.vue";
import AutoStatusPanel from "@/components/AutoStatusPanel.vue";
import TaskEditModal from "@/components/TaskEditModal.vue";
import HistoryTaskList from "@/components/HistoryTaskList.vue";
import CronJobList from "@/components/CronJobList.vue";
import imageBgUrl1 from "../../assets/cunny.png";
import imageBgUrl2 from "../../assets/cunny2.png";
export default {
  name: "SchedulerPanel",
  components: { CronJobList, HistoryTaskList, TaskEditModal, WaitingTaskList, AutoStatusPanel, RunningTaskPanel },
  props: ["runningTask", "waitingTaskList", "historyTaskList", "cronJobList"],
  data(){ 
    const savedCharacter = localStorage.getItem('activeCharacter') || '0';
    const activeChar = parseInt(savedCharacter);
    return { 
      imageBg: activeChar === 1 ? imageBgUrl2 : imageBgUrl1,
      activeCharacter: activeChar
    } 
  },
  mounted() {
    this.applyTheme();
  },
  methods: {
    toggleCharacter() {
      this.activeCharacter = this.activeCharacter === 0 ? 1 : 0;
      this.imageBg = this.activeCharacter === 1 ? imageBgUrl2 : imageBgUrl1;
      localStorage.setItem('activeCharacter', this.activeCharacter.toString());
      this.applyTheme();
    },
    applyTheme() {
      const root = document.documentElement;
      if (this.activeCharacter === 1) {
        root.style.setProperty('--bg-start', '#020810');
        root.style.setProperty('--bg-end', '#050f1a');
        root.style.setProperty('--surface', '#0a1420');
        root.style.setProperty('--surface-2', '#081018');
        root.style.setProperty('--accent', '#00d9ff');
        root.style.setProperty('--accent-2', '#5ce1ff');
        root.style.setProperty('--glow', '0 0 18px rgba(0,217,255,.25), 0 0 36px rgba(0,217,255,.12)');
      } else {
        root.style.setProperty('--bg-start', '#08000c');
        root.style.setProperty('--bg-end', '#120015');
        root.style.setProperty('--surface', '#141018');
        root.style.setProperty('--surface-2', '#100c13');
        root.style.setProperty('--accent', '#ff2da3');
        root.style.setProperty('--accent-2', '#ff5cc6');
        root.style.setProperty('--glow', '0 0 18px rgba(255,45,163,.25), 0 0 36px rgba(255,45,163,.12)');
      }
    }
  }
}
</script>

<style scoped>
.list-panel{display:flex;flex-direction:column;height:100%}
.list-panel .card{margin-bottom:0}
.image-card{flex:1 1 auto;display:flex}
.image-card .card-body{height:392px;min-height:392px;flex:0 0 auto;border-radius:12px;overflow:hidden}
.image-card .image-layer{width:100%;height:100%;min-height:100%;background:transparent var(--image-url) center/contain no-repeat !important;cursor:pointer;transition:transform 0.2s ease}
.image-card .image-layer:hover{transform:scale(1.02)}
.list-panel> .mb-3:last-child{margin-bottom:0}
.list-title{font-weight:700}
.list-empty{color:var(--muted)}
</style>