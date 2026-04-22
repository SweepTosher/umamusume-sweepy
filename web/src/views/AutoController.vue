<template>
  <div>
    <div class="row mb-3">
      <div class="col-12">
        <div class="section-card">
          <div class="row g-3">
            <div class="col-sm-3">
              <div class="stat-card">
                <div class="stat-label">Running</div>
                <div class="stat-value">{{ runningTask ? 1 : 0 }}</div>
              </div>
            </div>
            <div class="col-sm-3">
              <div class="stat-card">
                <div class="stat-label">Waiting</div>
                <div class="stat-value">{{ waitingTaskList.length }}</div>
              </div>
            </div>
            <div class="col-sm-3">
              <div class="stat-card">
                <div class="stat-label">History</div>
                <div class="stat-value">{{ careerDataCount }}/2000</div>
              </div>
            </div>
            <div class="col-sm-3">
              <div class="stat-card">
                <div class="stat-label">Turn</div>
                <div class="stat-value">{{ formattedDate }}</div>
              </div>
            </div>
          </div>
          <div class="row g-3 mt-2">
            <div class="col-sm-12">
              <div class="stat-card">
                <div class="stat-label">Facility Executions (Career)</div>
                <div class="stat-value" style="font-size:16px">
                  Spd: {{ facilityClicks.speed }} | Sta: {{ facilityClicks.stamina }} | Pow: {{ facilityClicks.power }} | Guts: {{ facilityClicks.guts }} | Wits: {{ facilityClicks.wits }}
                </div>
              </div>
            </div>
          </div>
          <div class="row g-3 mt-2">
            <div class="col-sm-6">
              <div class="stat-card">
                <div class="d-flex align-items-center justify-content-between">
                  <div>
                    <div class="stat-label">Repetitive-click recovery</div>
                    <div class="stat-value" style="font-size:18px">
                      {{ runtimeState.repetitive_count }} / {{ runtimeState.repetitive_threshold }}
                      <span class="small text-muted" style="margin-left:8px">(other: {{ runtimeState.repetitive_other_clicks }})</span>
                    </div>
                  </div>
                  <input type="number" min="1" class="form-control form-control-sm" style="width:80px" v-model.number="editRepetitive" @change="saveThresholds">
                </div>
              </div>
            </div>
            <div class="col-sm-6">
              <div class="stat-card">
                <div class="d-flex align-items-center justify-content-between">
                  <div>
                    <div class="stat-label">Screen Watchdog</div>
                    <div class="stat-value" style="font-size:18px">{{ runtimeState.watchdog_unchanged }} / {{ runtimeState.watchdog_threshold }}</div>
                  </div>
                  <input type="number" min="1" class="form-control form-control-sm" style="width:80px" v-model.number="editWatchdog" @change="saveThresholds">
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="runningTask" class="row mb-3">
      <div class="col-12">
        <div class="section-card d-flex align-items-center justify-content-between">
          <div class="d-flex align-items-center" style="gap:12px">
            <div class="status-pill"><span class="dot running"></span><span>Running</span></div>
            <div class="spot-text">
              <div class="spot-title">{{ runningTask.task_desc || 'Active Task' }}</div>
              <div class="spot-meta">Task ID: {{ runningTask.task_id || '-' }} • Scenario: {{ runningTask.attachment_data?.scenario || '-' }}</div>
            </div>
          </div>
          <div class="spot-actions">
            <button class="btn btn-sm btn--outline" @click="scrollToLogs">View Logs</button>
          </div>
        </div>
      </div>
    </div>

    <div class="row">
      <div class="col-4">
      <scheduler-panel 
          :waiting-task-list="waitingTaskList"
          :running-task="runningTask"
          :history-task-list="historyTaskList"
          :cron-job-list="cronJobList"
          :detected-skills="detectedSkills"
          :detected-portraits="detectedPortraits"
          :detected-items="detectedItems"
          :detected-shop-items="detectedShopItems"
        />
      </div>
      <div class="col-8">
        <log-panel 
          :log-content="logContent"
          :auto-log="autoLog"
          :toggle-auto-log="toggleAutoLog"
        />
      </div>
    </div>
  </div>
</template>

<script>
import SchedulerPanel from "../components/SchedulerPanel.vue";
import LogPanel from "../components/base/LogPanel.vue";
export default {
  name: "AutoController",
  components: { LogPanel, SchedulerPanel },
  data() {
    return {
      taskId: '0',
      runningTask: undefined,
      waitingTaskList: [],
      historyTaskList: [],
      cronJobList: [],
      taskList: [],
      logContent: "",
      autoLog: true,
      taskLogTimer: undefined,
       runtimeState: { repetitive_count: 0, repetitive_other_clicks: 0, repetitive_threshold: 11, watchdog_unchanged: 0, watchdog_threshold: 3 },
       editRepetitive: 11,
      editWatchdog: 3,
      detectedSkills: [],
      detectedPortraits: [],
       detectedItems: [],
       detectedShopItems: [],
       careerDataCount: 0,
       facilityClicks: { speed: 0, stamina: 0, power: 0, guts: 0, wits: 0 },
       careerDataTimer: null,
       currentDate: null,
       currentDateTimer: null,
       taskListTimer: null,
       runtimeStateTimer: null,
       shopItemsTimer: null,
       detectedItemsTimer: null,
       detectedSkillsTimer: null,
       detectedPortraitsTimer: null
     }
   },
  computed: {
    formattedDate(){
      if (this.currentDate === null) return '—';
      if (this.currentDate >= 73) return 'Finale';
      return `Day ${this.currentDate}`;
    }
   },
   mounted(){
     this.getTaskList();
     this.getTaskLog();
     this.pollRuntimeState();
     this.pollDetectedShopItems();
     this.fetchCareerDataCount();
     this.fetchCurrentDate();
     this.careerDataTimer = setInterval(this.fetchCareerDataCount, 3000);
     this.currentDateTimer = setInterval(this.fetchCurrentDate, 1000);
      this.taskListTimer = setInterval(this.getTaskList, 3000);
      this.runtimeStateTimer = setInterval(this.pollRuntimeState, 2000);
      this.shopItemsTimer = setInterval(this.pollDetectedShopItems, 5000);
      this.taskLogTimer = setInterval(this.getTaskLog, 1000);
      this.detectedItemsTimer = setInterval(this.pollDetectedItems, 3000);
      this.detectedSkillsTimer = setInterval(this.pollDetectedSkills, 3000);
      this.detectedPortraitsTimer = setInterval(this.pollDetectedPortraits, 3000);
      this.pollDetectedItems();
      this.pollDetectedSkills();
      this.pollDetectedPortraits();
   },
   methods:{
     fetchCareerDataCount() {
       this.axios.get('/api/career-data-count').then(res => {
         this.careerDataCount = res.data.count;
         if (res.data.facility_clicks) {
           this.facilityClicks = res.data.facility_clicks;
         }
       }).catch(() => {
         this.careerDataCount = 0;
       });
     },
     fetchCurrentDate(){
       this.axios.get('/api/current-date').then(res => {
         this.currentDate = res.data.date;
       }).catch(() => {
         this.currentDate = null;
       });
     },
     scrollToLogs(){
      const el = document.getElementById('scroll_text');
      if (el) el.focus();
    },
    getTaskList(){
      this.axios.get("/task").then(res=>{
        this.taskList = res.data;
        let waitingTaskList = []
        let historyTaskList = []
        let cronJobList = []
        let runningTask = undefined
        this.taskList.forEach(t=>{
          const mode = t['task_execute_mode']
          const status = t['task_status']
          if (mode === 2 || mode === 'TASK_EXECUTE_MODE_CRON_JOB') {
            if (status === 6 || status === 7) { cronJobList.push(t) }
          } else {
            if (status === 2) { runningTask = t }
            else if (status === 1) { waitingTaskList.push(t) }
            else if (status === 5 || status === 4 || status === 3) { historyTaskList.push(t) }
          }
        })
        this.waitingTaskList = waitingTaskList
        this.historyTaskList = historyTaskList
        this.runningTask = runningTask
        this.cronJobList = cronJobList
        if(this.runningTask === undefined){ this.taskId = '0' } else { this.taskId = runningTask['task_id'] }
      });
    },
    getTaskLog() {
      if (this.taskId !== '0') {
        this.axios.get("/log/" + this.taskId).then(res => { this.logContent = res.data.join('\n') });
      }
    },
    toggleAutoLog(){
      this.autoLog = !this.autoLog;
      if (this.autoLog) {
        if (this.taskLogTimer === undefined) { this.taskLogTimer = setInterval(this.getTaskLog,1000) }
      } else {
        if (this.taskLogTimer) { clearInterval(this.taskLogTimer); this.taskLogTimer = undefined }
      }
    },
    pollRuntimeState(){
      this.axios.get('/api/runtime-state').then(res=>{
        if (res && res.data){
          this.runtimeState = res.data
          this.editRepetitive = Number(this.runtimeState.repetitive_threshold || 11)
          this.editWatchdog = Number(this.runtimeState.watchdog_threshold || 3)
        }
      }).catch(()=>{})
    },
    saveThresholds(){
      const payload = {
        repetitive_threshold: Number(this.editRepetitive)||1,
        watchdog_threshold: Number(this.editWatchdog)||1
      }
      this.axios.post('/api/runtime-thresholds', payload).then(()=>{
      }).catch(()=>{})
    },
    pollDetectedSkills(){
      this.axios.get('/api/detected-skills').then(res=>{
        if (res && res.data && Array.isArray(res.data)){
          this.detectedSkills = res.data
        }
      }).catch(()=>{})
    },
    pollDetectedPortraits(){
      this.axios.get('/api/detected-portraits').then(res=>{
        if (res && res.data && Array.isArray(res.data)){
          this.detectedPortraits = res.data
        }
      }).catch(()=>{})
    },
    pollDetectedItems(){
      this.axios.get('/api/detected-items').then(res=>{
        if (res && res.data && Array.isArray(res.data)){
          this.detectedItems = res.data
        }
      }).catch(()=>{})
    },
    pollDetectedShopItems(){
      this.axios.get('/api/detected-shop-items').then(res=>{
        if (res && res.data && Array.isArray(res.data)){
          this.detectedShopItems = res.data
        }
      }).catch(()=>{})
    }
  },
  beforeUnmount(){
     if (this.careerDataTimer) clearInterval(this.careerDataTimer);
     if (this.currentDateTimer) clearInterval(this.currentDateTimer);
     if (this.taskListTimer) clearInterval(this.taskListTimer);
     if (this.runtimeStateTimer) clearInterval(this.runtimeStateTimer);
     if (this.shopItemsTimer) clearInterval(this.shopItemsTimer);
     if (this.taskLogTimer) clearInterval(this.taskLogTimer);
     if (this.detectedItemsTimer) clearInterval(this.detectedItemsTimer);
     if (this.detectedSkillsTimer) clearInterval(this.detectedSkillsTimer);
     if (this.detectedPortraitsTimer) clearInterval(this.detectedPortraitsTimer);
   }
 }
</script>

<style scoped>
.stat-label{font-size:12px;color:var(--muted)}
.stat-value{font-size:22px;font-weight:700;color:#fff}
.spot-title{font-weight:700;color:#fff}
.spot-meta{font-size:12px;color:var(--muted)}
</style>
