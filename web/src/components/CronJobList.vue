<template>
  <div class="cron-job-list">
    <div class="card">
      <div class="card-body">
        <div class="d-flex bd-highlight">
          <h5 class="card-title">Scheduled Tasks</h5>
        </div>
      </div>
      <TaskList v-bind:task-list="cronJobList" v-bind:no-data-label="'No scheduled tasks'"></TaskList>
    </div>
  </div>
</template>

<script>
import TaskList from "./TaskList.vue";

export default {
  name: "CronJobList",
  props:["cronJobList"],
  components: {TaskList},
  data:function (){
    return{
    }
  }
}
</script>

