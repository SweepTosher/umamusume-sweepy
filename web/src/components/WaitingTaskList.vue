<template>
  <div>
    <div class="card">
      <div class="card-body">
        <div class="d-flex align-items-center">
          <h5 class="mb-0">Waiting</h5>
        </div>
      </div>
      <TaskList :task-list="waitingTaskList" :no-data-label="'No waiting tasks'"></TaskList>
    </div>
  </div>
</template>

<script>
import TaskList from "./TaskList.vue"
export default {
  name: "WaitingTaskList",
  props:["waitingTaskList"],
  components: {TaskList},
  data(){ return{} }
}
</script>

<style scoped>
.card-body{border-bottom:1px solid rgba(255,255,255,.06)}
</style>