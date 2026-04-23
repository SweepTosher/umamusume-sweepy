<template>
  <div>
    <div class="card">
      <div class="card-body">
        <div class="d-flex align-items-center">
          <h5 class="mb-0">Completed Tasks</h5>
        </div>
      </div>
      <TaskList :task-list="historyTaskList" :no-data-label="'No completed tasks'"></TaskList>
    </div>
  </div>
</template>

<script>
import TaskList from "./TaskList.vue";

export default {
  name: "HistoryTaskPanel",
  props:["historyTaskList"],
  components: {TaskList},
  data(){ return{} }
}
</script>

