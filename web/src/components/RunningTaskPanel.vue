<template>
  <div>
    <div class="card">
      <div v-if="runningTask === undefined" class="card-body">
        <div class="d-flex align-items-center">
          <h5 class="mb-0">No running tasks</h5>
        </div>
      </div>
      <div v-if="runningTask !== undefined" class="card-body">
        <div class="d-flex align-items-center" style="gap:12px">
          <h5 class="mb-0">Currently Running: {{runningTask['task_desc']}}</h5>
          <span class="ml-auto"><i class="fa fa-cog fa-lg"></i></span>
        </div>
        <task-detail-info-handler :task="runningTask"></task-detail-info-handler>
      </div>
    </div>
  </div>
</template>

<script>
import TaskDetailInfoHandler from "./base/TaskDetailInfoHandler.vue";
export default {
  name: "RunningTaskPanel",
  props:["runningTask"],
  data(){ return{} },
  components: { TaskDetailInfoHandler }
}
</script>

<style scoped>
</style>