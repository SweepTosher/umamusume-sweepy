<template>
  <div id="app">
    <div class="app-frame">
      <div class="container-fluid">
        <router-view/>
        <manual-skill-notification-modal 
          v-model:show="showManualSkillNotification"
          @confirm="handleManualSkillConfirm"
          @cancel="handleManualSkillCancel"
        />
      </div>
    </div>
  </div>
</template>
<script>
import ManualSkillNotificationModal from '@/components/ManualSkillNotificationModal.vue'
import axios from '@/util/axiosConf.js'
import '@/assets/theme.css'

export default {
  name: 'App',
  components: {
    ManualSkillNotificationModal
  },
  data:function(){
    return{
      error:'',
      success:'',
      showManualSkillNotification: false
    }
  },
  mounted (){
    this.setupWebSocket();
    this.checkForRepoUpdate();
  },
  methods: {
    setupWebSocket() {
      this.checkForManualSkillNotification();
    },
    checkForRepoUpdate(){
      axios.get('/api/update-status', null, false)
        .then(res => {
          if (res && res.data && res.data.has_update){
            if (res.data.preset_redo) {
              alert("The next update requires you to redo your presets");
            } else {
              alert("There's a update available for this repo. Please run start.bat");
            }
          }
        })
        .catch(()=>{});
    },
    checkForManualSkillNotification() {
      setInterval(() => {
        axios.get('/api/manual-skill-notification-status', null, false)
          .then(response => {
            if (response.data.show) {
              this.showManualSkillNotification = true;
            }
          })
          .catch(() => {});
      }, 1000);
    },
    handleManualSkillConfirm() {
      axios.post('/api/manual-skill-notification-confirm', {}, false)
        .then(() => {
          this.showManualSkillNotification = false;
        })
        .catch(() => {});
    },
    handleManualSkillCancel() {
      axios.post('/api/manual-skill-notification-cancel', {}, false)
        .then(() => {
          this.showManualSkillNotification = false;
        })
        .catch(() => {});
    }
  },
  watch:{

  }
}
</script>
<style>
#app { color: var(--text); }
.badge{ font-size:11px }
.app-frame{min-height:100vh;position:relative}
</style>
