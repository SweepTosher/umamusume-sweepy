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
          <span class="ml-auto edit-task-btn" @click="onEditTask"><i class="fa fa-cog fa-lg"></i></span>
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
  components: { TaskDetailInfoHandler },
  methods: {
    onEditTask() {
      this.$emit('edit-task', this.runningTask);
    }
  }
}
</script>

<style scoped>
.edit-task-btn {
  cursor: pointer;
  opacity: 0.7;
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.edit-task-btn:hover {
  opacity: 1;
  transform: rotate(45deg);
}
</style>