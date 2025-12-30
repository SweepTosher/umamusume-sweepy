<template>
  <div>
    <div v-if="taskList === undefined || taskList.length === 0">
      <div class="card-body list-empty">
        {{noDataLabel}}
      </div>
    </div>
    <div v-if="taskList !== undefined">
      <ul class="list-group list-group-flush">
        <li v-for="task in taskList" class="list-group-item">
          <div>
            <div class="d-flex align-items-center">
              <h6 class="mb-0">{{task['task_desc']}}</h6>
            </div>
            <task-detail-info-handler :task="task"></task-detail-info-handler>
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>

<script>
import TaskDetailInfoHandler from "./base/TaskDetailInfoHandler.vue";
export default {
  name: "TaskList",
  components: {TaskDetailInfoHandler},
  props:["taskList", "noDataLabel"],
  data(){ return{} }
}
</script>

<style scoped>
.list-group-item{padding:12px 14px}
</style>